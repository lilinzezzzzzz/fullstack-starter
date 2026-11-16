import json
import os
import signal
import socket
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
import uvicorn
from pydantic import ValidationError

from app.config import CONFIG_FILE, Settings, load_settings
from app.utils.database_lock import ServiceError
from entrypoints import service, service_control
from entrypoints.service_control import InstanceControl, instance_active, runtime_path, service_lock
from migrations.operations import upgrade_database
from tests.helpers import read_config, save_config, write_config
from tests.test_service import foreground_service, unused_port, wait_for_service

pytestmark = pytest.mark.usefixtures("service_project")


def service_command(config: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            str(service_control.PROJECT_ROOT / "backend/entrypoints/service.sh"),
            command,
            "--config",
            str(config),
        ],
        cwd=config.parent,
        capture_output=True,
        text=True,
        timeout=15,
    )


def isolated_config(directory: Path) -> Path:
    config = write_config(directory)
    data = read_config(config)
    data["server"].update(port=unused_port(), graceful_shutdown_seconds=1.0)
    data["service"].update(startup_timeout_seconds=5.0, stop_timeout_seconds=4.0)
    save_config(config, data)
    return config


@contextmanager
def background_service(config: Path) -> Generator[Settings]:
    try:
        started = service_command(config, "start")
        assert started.returncode == 0, started.stdout + started.stderr
        yield load_settings(config)
    finally:
        stopped = service_command(config, "stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr


def test_command_is_required_and_old_implicit_run_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for arguments in ([], ["--config", str(CONFIG_FILE)], ["invalid"]):
        monkeypatch.setattr(sys, "argv", ["service", *arguments])
        with pytest.raises(SystemExit) as error:
            service.main()
        assert error.value.code == 2


def test_default_configuration_is_app_toml(service_project: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        ["sh", str(service_project / "backend/entrypoints/service.sh"), "status"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert result.stdout.strip() == "stopped"
    assert (service_project / ".run/run.lock").exists()
    assert not (service_project / ".data").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_timeout_seconds", 0.0),
        ("startup_timeout_seconds", float("inf")),
        ("stop_timeout_seconds", -1.0),
        ("stop_timeout_seconds", 10.0),
    ],
)
def test_invalid_service_timeouts_are_rejected(tmp_path: Path, field: str, value: float) -> None:
    config = write_config(tmp_path)
    data = read_config(config)
    data["service"][field] = value
    save_config(config, data)
    with pytest.raises(ValidationError):
        load_settings(config)


@pytest.mark.parametrize(
    "field", ["data_dir", "backup_directory", "logging.directory", "testing.temporary_directory"]
)
@pytest.mark.parametrize("directory", [".run", ".run/nested", ".RUN"])
def test_private_and_temporary_paths_cannot_overlap_project_runtime(
    tmp_path: Path,
    service_project: Path,
    field: str,
    directory: str,
) -> None:
    config = write_config(tmp_path)
    data = read_config(config)
    section, separator, name = field.partition(".")
    destination = str(service_project / directory)
    if separator:
        data[section][name] = destination
    else:
        data[field] = destination
    save_config(config, data)
    with pytest.raises(ValidationError, match="service runtime directory"):
        load_settings(config)


@pytest.mark.integration
def test_background_lifecycle_is_idempotent_and_preserves_shutdown_logs(tmp_path: Path) -> None:
    config = isolated_config(tmp_path / "configuration with spaces 中文")
    settings = load_settings(config)
    upgrade_database(settings)
    with background_service(config):
        state_path = runtime_path("instance.json")
        initial = json.loads(state_path.read_text())
        assert state_path.parent == service_control.PROJECT_ROOT / ".run"
        assert {path.name for path in state_path.parent.iterdir()} == {
            "instance.json",
            "run.lock",
            "control.lock",
            "console.log",
        }
        assert datetime.fromisoformat(initial["started_at"]).utcoffset().total_seconds() == 0
        assert initial["command"][1:] == [
            "-m",
            "entrypoints.service",
            "run",
            "--config",
            str(config.resolve()),
        ]
        assert initial["config"] == str(config.resolve())
        assert initial["project"] == str(service_control.PROJECT_ROOT)
        assert state_path.stat().st_mode & 0o777 == 0o600
        assert service_command(config, "status").returncode == 0
        duplicate = service_command(config, "start")
        assert duplicate.returncode == 0 and "already running" in duplicate.stdout
        assert json.loads(state_path.read_text())["pid"] == initial["pid"]
        with foreground_service(config) as (duplicate_run, output):
            assert duplicate_run.wait(timeout=10) != 0
            assert "in progress" in output.read_text()
        with pytest.raises(ServiceError, match="in progress"):
            upgrade_database(settings)
        restarted = service_command(config, "restart")
        assert restarted.returncode == 0, restarted.stderr
        assert json.loads(state_path.read_text())["pid"] != initial["pid"]
        assert service_command(config, "status").returncode == 0
    assert not runtime_path("instance.json").exists()
    assert not instance_active()
    assert service_command(config, "status").returncode == 3
    assert "already stopped" in service_command(config, "stop").stdout
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert contents.count("Application shutdown complete") == 2
    assert contents.count("Finished server process") == 2
    output = runtime_path("console.log").read_text()
    assert "resource_tracker" not in output
    assert "leaked semaphore" not in output
    upgrade_database(settings)


@pytest.mark.integration
def test_foreground_instance_can_be_queried_and_stopped(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    settings = load_settings(config)
    upgrade_database(settings)
    with foreground_service(config) as (process, output):
        wait_for_service(process, settings, output)
        assert service_command(config, "status").returncode == 0
        assert service_command(config, "stop").returncode == 0
        assert process.wait(timeout=5) in (0, 130)
    assert not instance_active()


@pytest.mark.integration
def test_restart_applies_changed_config_but_other_config_cannot_stop_it(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    settings = load_settings(config)
    upgrade_database(settings)
    with background_service(config):
        other_config = tmp_path / "other.toml"
        other_config.write_bytes(config.read_bytes())
        for command in ("start", "status", "stop", "restart"):
            rejected = service_command(other_config, command)
            assert rejected.returncode == 1
            assert "different project or configuration" in rejected.stderr
        data = read_config(config)
        data["application"]["title"] = "changed service"
        save_config(config, data)
        assert service_command(config, "start").returncode == 1
        state = service_command(config, "status")
        assert state.returncode == 1 and "config-changed" in state.stdout
        assert service_command(config, "restart").returncode == 0
        assert service_command(config, "status").returncode == 0


@pytest.mark.integration
def test_different_database_and_port_cannot_start_a_second_project_instance(tmp_path: Path) -> None:
    first = isolated_config(tmp_path / "first")
    second = isolated_config(tmp_path / "second")
    first_settings = load_settings(first)
    second_settings = load_settings(second)
    upgrade_database(first_settings)
    upgrade_database(second_settings)
    with background_service(first):
        before = runtime_path("instance.json").read_bytes()
        for command in ("start", "run"):
            rejected = service_command(second, command)
            assert rejected.returncode == 1
        assert runtime_path("instance.json").read_bytes() == before
        assert service_command(first, "status").returncode == 0
        assert not list(second_settings.data_dir.glob("*.service.*"))
        assert not second_settings.logging.directory.exists()


def test_project_runtime_directory_cannot_be_redirected_by_symlink(
    tmp_path: Path,
    service_project: Path,
) -> None:
    target = tmp_path / "redirected-runtime"
    target.mkdir()
    (service_project / ".run").symlink_to(target, target_is_directory=True)
    config = isolated_config(tmp_path)
    with pytest.raises(ValidationError, match=".run must not be a symlink"):
        load_settings(config)
    assert not list(target.iterdir())


@pytest.mark.parametrize("kind", ["database", "database-lock", "application-log"])
def test_private_file_symlinks_cannot_alias_service_state(tmp_path: Path, kind: str) -> None:
    config = isolated_config(tmp_path)
    settings = load_settings(config)
    target = runtime_path("instance.json")
    target.parent.mkdir()
    if kind == "database":
        alias = settings.database_path
    elif kind == "database-lock":
        alias = settings.database_path.with_suffix(settings.database_path.suffix + ".lock")
    else:
        alias = settings.logging.directory / settings.logging.filename
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to(target)
    with pytest.raises(ValidationError, match="service runtime directory"):
        load_settings(config)
    assert not target.exists()


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["missing-database", "missing-frontend", "unhealthy"])
def test_failed_background_start_cleans_up_owned_process(tmp_path: Path, failure: str) -> None:
    config = isolated_config(tmp_path)
    data = read_config(config)
    if failure == "missing-frontend":
        data["serve_frontend"] = True
    elif failure == "unhealthy":
        data["allowed_hosts"] = []
        data["service"]["startup_timeout_seconds"] = 1.0
    save_config(config, data)
    settings = load_settings(config)
    if failure != "missing-database":
        upgrade_database(settings)
    try:
        failed = service_command(config, "start")
        assert failed.returncode == 1, failed.stdout + failed.stderr
        assert "startup" in failed.stderr.lower()
        assert not instance_active()
        assert not runtime_path("instance.json").exists()
        assert service_command(config, "status").returncode == 3
        if failure == "missing-database":
            assert not settings.database_path.exists()
    finally:
        service_command(config, "stop")
    upgrade_database(settings)


@pytest.mark.integration
def test_invalid_instance_credentials_never_signal_a_running_service(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    settings = load_settings(config)
    upgrade_database(settings)
    with background_service(config):
        path = runtime_path("instance.json")
        original = path.read_bytes()
        record = json.loads(original)
        with socket.create_connection(("127.0.0.1", record["port"]), timeout=1) as connection:
            connection.sendall(
                json.dumps({"token": "错误凭据", "command": "stop"}).encode() + b"\n"
            )
            assert connection.recv(1) == b""
        assert service_command(config, "status").returncode == 0
        try:
            for field, value in (("token", "0" * 64), ("pid", os.getpid())):
                corrupted = json.loads(original)
                corrupted[field] = value
                path.write_text(json.dumps(corrupted))
                rejected = service_command(config, "stop")
                assert rejected.returncode == 1
                assert "no signal sent" in rejected.stderr
                # HTTP 仍然可用；实例没有因凭据或 PID 不匹配而停止。
                assert service.healthy(settings, 1.0)
        finally:
            path.write_bytes(original)
        assert service_command(config, "status").returncode == 0


@pytest.mark.integration
def test_stale_record_does_not_target_a_reused_pid(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    settings = load_settings(config)
    settings.data_dir.mkdir()
    path = runtime_path("instance.json")
    path.parent.mkdir()
    path.write_text(json.dumps({"pid": os.getpid(), "port": 1, "token": "stale"}))
    assert service_command(config, "status").returncode == 3
    assert service_command(config, "stop").returncode == 0
    upgrade_database(settings)
    with background_service(config):
        assert json.loads(path.read_text())["pid"] != os.getpid()
        assert service_command(config, "status").returncode == 0


@pytest.mark.integration
def test_restart_does_not_start_after_stop_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = isolated_config(tmp_path)
    data = read_config(config)
    data["server"]["graceful_shutdown_seconds"] = 0.01
    data["service"]["stop_timeout_seconds"] = 0.15
    save_config(config, data)
    settings = load_settings(config)
    signals = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    server = uvicorn.Server(uvicorn.Config("unused"))
    control = InstanceControl(settings, config.resolve(), server)
    with service_lock(runtime_path("run.lock")):
        try:
            control.start()
            failed = service_command(config, "restart")
            assert failed.returncode == 1
            assert "Stop timed out" in failed.stderr
            assert signals == [(os.getpid(), signal.SIGINT)]
            assert runtime_path("instance.json").exists()
            assert not runtime_path("console.log").exists()
        finally:
            control.close()


@pytest.mark.integration
def test_command_lock_rejects_concurrent_mutations(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    with service_lock(runtime_path("control.lock")):
        for command in ("start", "stop", "restart"):
            result = service_command(config, command)
            assert result.returncode == 1
            assert "in progress" in result.stderr
        assert service_command(config, "status").returncode == 3
    assert not runtime_path("console.log").exists()
    assert not runtime_path("instance.json").exists()


@pytest.mark.integration
def test_failed_background_start_never_touches_occupied_port(tmp_path: Path) -> None:
    config = isolated_config(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        data = read_config(config)
        data["server"]["port"] = listener.getsockname()[1]
        save_config(config, data)
        settings = load_settings(config)
        upgrade_database(settings)
        try:
            result = service_command(config, "start")
            assert result.returncode == 1
            assert not instance_active()
            assert listener.getsockname()[1] == settings.server.port
            assert not runtime_path("instance.json").exists()
        finally:
            service_command(config, "stop")
    upgrade_database(settings)
