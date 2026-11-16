"""两项目共用的服务契约；仅配置 fixture 适配各自的业务 Settings。"""

import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from http.client import BadStatusLine
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
import uvicorn
from pydantic import ValidationError

from app.config import Settings, load_settings, load_settings_snapshot
from app.utils.path_safety import validate_runtime_paths
from entrypoints import service, service_control
from entrypoints.service_control import (
    ServiceController,
    StartupSnapshot,
    instance_active,
    is_healthy,
    read_record,
    read_startup_snapshot,
    runtime_path,
    service_lock,
)
from migrations.operations import migration_config, upgrade_database
from tests.helpers import read_config, save_config, write_config
from tests.service_helpers import (
    foreground_service,
    isolated_service_project,
    run_service_command,
    wait_for_service,
)

pytestmark = pytest.mark.usefixtures("service_project")


def isolated_config(directory):
    overrides = {"security": {"api_token": ""}} if "security" in Settings.model_fields else {}
    path = write_config(directory, **overrides)
    data = read_config(path)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        data["server"]["port"] = listener.getsockname()[1]
    data["server"]["graceful_shutdown_seconds"] = 0.1
    data["service"].update(startup_timeout_seconds=5.0, stop_timeout_seconds=2.0)
    save_config(path, data)
    return path


def command(project, action, path=None):
    arguments = ["sh", str(project / "entrypoints/service.sh"), action]
    if path is not None:
        arguments.extend(["--config", str(path)])
    return run_service_command(
        arguments, cwd=project.parent, command_timeout=60, shutdown_timeout=5
    )


def observed_command(project, marker, action, path):
    code = f"""
from contextlib import contextmanager
from pathlib import Path
from entrypoints import service, service_control
original_lock = service_control.service_lock
@contextmanager
def observe(path, timeout=0):
    if path.name == "control.lock":
        Path({str(marker)!r}).touch()
    with original_lock(path, timeout):
        yield
service.service_lock = service_control.service_lock = observe
raise SystemExit(service.main())
"""
    return subprocess.Popen(
        [str(project / "backend/.venv/bin/python"), "-c", code, action, "--config", str(path)],
        cwd=project / "backend",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def wait_for_marker(marker, process):
    deadline = time.monotonic() + 15
    while not marker.exists():
        assert process.poll() is None, process.communicate()
        assert time.monotonic() < deadline, "Command did not reach the control lock"
        time.sleep(0.01)


def finish_child(child):
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGINT)
        child.communicate(timeout=10)


@pytest.mark.integration
@pytest.mark.parametrize(
    "actions",
    [("start", "start"), ("start", "run"), ("run", "start"), ("run", "run")],
    ids=["start-start", "start-run", "run-start", "run-run"],
)
def test_first_concurrent_launches_share_one_instance(service_project, tmp_path, actions):
    configs = [isolated_config(tmp_path / name) for name in ("first", "second")]
    for path in configs:
        upgrade_database(load_settings(path))
    processes = []
    try:
        assert read_record() is None
        # 两个真实 Shell 入口都已启动后才放开检查/登记阶段，初始状态均无实例。
        with service_lock(runtime_path("control.lock")):
            for action, path in zip(actions, configs, strict=True):
                processes.append(
                    subprocess.Popen(
                        [
                            "sh",
                            str(service_project / "entrypoints/service.sh"),
                            action,
                            "--config",
                            str(path),
                        ],
                        cwd=tmp_path,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        start_new_session=True,
                    )
                )
            assert all(process.poll() is None for process in processes)
            assert read_record() is None

        deadline = time.monotonic() + 20
        record = None
        while time.monotonic() < deadline:
            record = read_record()
            if record is not None:
                break
            time.sleep(0.02)
        assert record is not None
        assert record.config in {str(path.resolve()) for path in configs}
        for process, action, path in zip(processes, actions, configs, strict=True):
            if action == "run" and process.pid == record.pid:
                assert process.poll() is None
                continue
            stdout, stderr = process.communicate(timeout=45)
            assert process.returncode == 0, stdout + stderr
            if str(path.resolve()) != record.config:
                assert "already running" in stdout
        assert read_record() == record
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if is_healthy(record.url):
                break
            time.sleep(0.02)
        assert command(service_project, "status").returncode == 0

        assert command(service_project, "stop").returncode == 0
        for process, action in zip(processes, actions, strict=True):
            stdout, stderr = process.communicate(timeout=10)
            expected = 130 if action == "run" and process.pid == record.pid else 0
            assert process.returncode == expected, stdout + stderr
        assert read_record() is None
    finally:
        try:
            assert command(service_project, "stop").returncode == 0
        finally:
            for process in processes:
                finish_child(process)


@pytest.mark.integration
@pytest.mark.parametrize("action", ["start", "run"])
def test_existing_instance_ignores_missing_invalid_and_other_configuration(
    service_project, tmp_path, action
):
    first = isolated_config(tmp_path / "first")
    other = isolated_config(tmp_path / "other")
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("invalid = [")
    upgrade_database(load_settings(first))
    try:
        started = command(service_project, "start", first)
        assert started.returncode == 0, started.stderr
        original = read_record()
        assert original is not None
        for target in (other, invalid, tmp_path / "missing.toml", None):
            existing = command(service_project, action, target)
            assert existing.returncode == 0, existing.stderr
            assert "already running" in existing.stdout
            assert original.config in existing.stdout
            assert read_record() == original
        assert not load_settings(other).logging.directory.exists()
    finally:
        assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("change", ["deleted", "invalid", "modified"])
def test_status_stop_only_use_saved_instance(service_project, tmp_path, change):
    path = isolated_config(tmp_path / "source")
    settings = load_settings(path)
    upgrade_database(settings)
    try:
        assert command(service_project, "start", path).returncode == 0
        (service_project / "configs/app.toml").unlink()
        if change == "deleted":
            path.unlink()
        elif change == "invalid":
            path.write_text("invalid = [")
        else:
            data = read_config(path)
            data["server"]["port"] = 1
            save_config(path, data)
        status = command(service_project, "status")
        assert status.returncode == 0, status.stderr
        assert f":{settings.server.port}" in status.stdout
        assert command(service_project, "stop", path).returncode == 0
        assert command(service_project, "status").returncode == 3
        assert command(service_project, "stop").returncode == 0
    finally:
        assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("default", [False, True])
def test_restart_switches_configuration_or_uses_default(service_project, tmp_path, default):
    first = isolated_config(tmp_path / "first")
    target = isolated_config(tmp_path / "target")
    data = read_config(target)
    data["application"]["title"] = "restarted configuration"
    save_config(target, data)
    if default:
        save_config(service_project / "configs/app.toml", read_config(target))
        target = service_project / "configs/app.toml"
    for path in (first, target):
        upgrade_database(load_settings(path))
    try:
        assert command(service_project, "start", first).returncode == 0
        previous = read_record()
        first.unlink()
        result = command(service_project, "restart", None if default else target)
        assert result.returncode == 0, result.stderr
        current = read_record()
        assert current is not None and previous is not None
        assert current.config == str(target.resolve())
        assert current.token != previous.token
        assert command(service_project, "status").returncode == 0
        with urlopen(current.url + "/openapi.json", timeout=3) as response:
            assert json.load(response)["info"]["title"] == "restarted configuration"
    finally:
        assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("change", ["invalid", "deleted"])
def test_restart_reads_target_after_waiting_for_lock(service_project, tmp_path, change):
    first = isolated_config(tmp_path / "first")
    target = isolated_config(tmp_path / "target")
    upgrade_database(load_settings(first))
    child = None
    try:
        assert command(service_project, "start", first).returncode == 0
        previous = read_record()
        marker = tmp_path / "waiting"
        with service_lock(runtime_path("control.lock")):
            child = observed_command(service_project, marker, "restart", target)
            wait_for_marker(marker, child)
            if change == "deleted":
                target.unlink()
            else:
                target.write_text("invalid = [")
        stdout, stderr = child.communicate(timeout=45)
        assert child.returncode == 1, stdout + stderr
        assert read_record() == previous
        assert command(service_project, "status").returncode == 0
    finally:
        finish_child(child)
        assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("change", ["invalid", "deleted", "different_values"])
def test_restart_child_consumes_frozen_document(service_project, tmp_path, monkeypatch, change):
    first = isolated_config(tmp_path / "first")
    target = isolated_config(tmp_path / "target")
    expected = load_settings(target)
    for path in (first, target):
        upgrade_database(load_settings(path))
    controller = ServiceController(config_file=target)
    original_stop = controller.stop

    def change_after_validation():
        assert controller.settings is not None
        if change == "deleted":
            target.unlink()
        elif change == "invalid":
            target.write_text("invalid = [")
        else:
            data = read_config(target)
            data["data_dir"] = str(tmp_path / "uninitialized")
            data["server"]["port"] = 1
            data["application"]["title"] = "must not replace the frozen title"
            save_config(target, data)
        return original_stop()

    try:
        assert command(service_project, "start", first).returncode == 0
        monkeypatch.setattr(controller, "stop", change_after_validation)
        assert controller.execute("restart") == 0
        current = read_record()
        assert current is not None
        assert current.url.endswith(f":{expected.server.port}")
        assert current.config == str(target.resolve())
        assert command(service_project, "status").returncode == 0
        with urlopen(current.url + expected.application.openapi_path, timeout=3) as response:
            assert json.load(response)["info"]["title"] == expected.application.title
        assert not (tmp_path / "uninitialized").exists()
    finally:
        assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("action", ["start", "run", "status", "stop", "restart"])
def test_interrupted_lock_wait_returns_130_and_preserves_instance(
    service_project, tmp_path, action
):
    path = isolated_config(tmp_path / "source")
    upgrade_database(load_settings(path))
    child = None
    try:
        assert command(service_project, "start", path).returncode == 0
        previous = read_record()
        marker = tmp_path / "waiting"
        with service_lock(runtime_path("control.lock")):
            child = observed_command(service_project, marker, action, path)
            wait_for_marker(marker, child)
            os.killpg(child.pid, signal.SIGINT)
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 130, stdout + stderr
            assert "Traceback" not in stderr
        assert read_record() == previous
    finally:
        finish_child(child)
        assert command(service_project, "stop").returncode == 0


@pytest.mark.parametrize("action", ["start", "run", "status", "stop"])
@pytest.mark.integration
def test_runtime_guard_does_not_need_valid_configuration(service_project, tmp_path, action):
    outside = tmp_path / "outside"
    outside.mkdir()
    (service_project / ".run").symlink_to(outside, target_is_directory=True)
    result = command(service_project, action, tmp_path / "missing.toml")
    assert result.returncode == 1
    assert "real directory" in result.stderr
    assert not list(outside.iterdir())
    (service_project / ".run").unlink()


def test_snapshot_preserves_raw_toml_without_reopening_source(service_project, tmp_path):
    path = isolated_config(tmp_path / "source")
    path.write_bytes(path.read_bytes() + b"\n# synthetic-sensitive-snapshot-comment\n")
    expected, document = load_settings_snapshot(path)
    controller = ServiceController(config_file=path)
    payload = controller.startup_snapshot()
    path.unlink()
    packet = StartupSnapshot.model_validate_json(payload)
    assert packet.document.encode() == document
    with tempfile.TemporaryFile(dir=tmp_path) as source:
        source.write(payload)
        source.seek(0)
        descriptor = os.dup(source.fileno())
        restored, original_payload = read_startup_snapshot(descriptor)
    assert restored.model_dump(mode="json") == expected.model_dump(mode="json")
    assert restored._source_file == expected._source_file
    assert original_payload == payload
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize(
    "section,field", [("service", "pid_file"), ("logging", "bootstrap_filename")]
)
def test_obsolete_runtime_path_configuration_is_rejected(tmp_path, section, field):
    path = isolated_config(tmp_path / "obsolete")
    data = read_config(path)
    data[section][field] = "unused"
    save_config(path, data)
    with pytest.raises(ValidationError):
        load_settings(path)


def test_invalid_snapshot_does_not_echo_document(tmp_path):
    with tempfile.TemporaryFile(dir=tmp_path) as source:
        source.write(b'{"config":"/synthetic/test.toml","document":"synthetic-secret = ["}')
        source.seek(0)
        with pytest.raises(RuntimeError, match="Invalid startup snapshot") as error:
            read_startup_snapshot(os.dup(source.fileno()))
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("directory", ["private", "private/synthetic", "PRIVATE/synthetic"])
def test_private_project_tree_cannot_be_public(service_project, tmp_path, directory):
    path = isolated_config(tmp_path / "source")
    data = read_config(path)
    data["frontend_dir"] = str(service_project / directory)
    data["frontend_clean_output"] = False
    save_config(path, data)
    with pytest.raises(ValidationError, match="private|protected"):
        load_settings(path)


@pytest.mark.parametrize("alias", ["public-output", "private-root"])
def test_private_project_tree_aliases_cannot_be_public(service_project, tmp_path, alias):
    path = isolated_config(tmp_path / "source")
    private = service_project / "private"
    if alias == "public-output":
        private.mkdir()
        output = tmp_path / "output-alias"
        output.symlink_to(private / "synthetic", target_is_directory=True)
    else:
        target = tmp_path / "private-target"
        target.mkdir()
        private.symlink_to(target, target_is_directory=True)
        output = target / "synthetic"
    data = read_config(path)
    data.update(frontend_dir=str(output), frontend_clean_output=False)
    save_config(path, data)
    with pytest.raises(ValidationError, match="private|protected"):
        load_settings(path)


@pytest.mark.parametrize("output", ["default", "custom"])
def test_private_storage_remains_valid_with_separate_public_output(
    service_project, tmp_path, output
):
    path = isolated_config(tmp_path / "source")
    data = read_config(path)
    data.update(
        frontend_dir=str(
            service_project / "frontend/dist" if output == "default" else tmp_path / "public"
        ),
        frontend_clean_output=False,
        data_dir=str(service_project / "private/data"),
        backup_directory=str(service_project / "private/backups"),
    )
    data["logging"]["directory"] = str(service_project / "private/logs")
    if "research" in data:
        data["research"]["storage"]["workflow_dir"] = str(service_project / "private/workflow")
    save_config(path, data)
    settings = load_settings(path)
    assert settings.backup_directory == service_project / "private/backups"


@pytest.mark.integration
@pytest.mark.parametrize("signum,expected", [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_foreground_signals_clean_state_and_shutdown_logs(
    service_project, tmp_path, signum, expected
):
    path = isolated_config(tmp_path / "source")
    settings = load_settings(path)
    upgrade_database(settings)
    with foreground_service(path) as (child, output):
        wait_for_service(child, settings, output)
        os.killpg(child.pid, signum)
        assert child.wait(timeout=settings.service.stop_timeout_seconds) == expected
    assert not instance_active()
    assert not runtime_path("instance.json").exists()
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert "Application shutdown complete" in contents
    assert "Finished server process" in contents
    upgrade_database(settings)


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["protocol", "malformed", "project", "permissions"])
def test_invalid_active_record_is_never_adopted(service_project, tmp_path, monkeypatch, kind):
    path = isolated_config(tmp_path / "source")
    settings = load_settings(path)
    signals = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    server = uvicorn.Server(uvicorn.Config("unused"))
    control = service_control.InstanceControl(settings, server, "synthetic-fingerprint")
    with service_lock(runtime_path("run.lock")):
        control.start()
        record_file = runtime_path("instance.json")
        original = record_file.read_bytes()
        try:
            data = json.loads(original)
            if kind == "protocol":
                data["protocol"] = 99
            elif kind == "project":
                data["project"] = str(tmp_path / "original-project")
            record_file.write_bytes(b"{" if kind == "malformed" else json.dumps(data).encode())
            if kind == "permissions":
                record_file.chmod(0o644)
            before = record_file.read_bytes()
            for action in ("start", "run", "status", "stop", "restart"):
                result = command(service_project, action, path)
                assert result.returncode == 1, result.stdout + result.stderr
                assert record_file.read_bytes() == before
                assert "Traceback" not in result.stderr
                if kind == "project":
                    assert "original project path and version" in result.stderr
            assert not signals
        finally:
            record_file.write_bytes(original)
            record_file.chmod(0o600)
            control.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "filename",
    ["instance.json", "instance.json.pending", "console.log", "run.lock", "control.lock"],
)
def test_runtime_file_symlinks_are_rejected_for_every_command(service_project, tmp_path, filename):
    outside = tmp_path / "synthetic-target"
    outside.write_text("must remain unchanged")
    directory = service_project / ".run"
    directory.mkdir()
    alias = directory / filename
    alias.symlink_to(outside)
    try:
        for action in ("start", "run", "status", "stop", "restart"):
            result = command(service_project, action, tmp_path / "missing.toml")
            assert result.returncode == 1
            assert "regular file" in result.stderr
        assert outside.read_text() == "must remain unchanged"
    finally:
        alias.unlink()


@pytest.mark.integration
def test_restart_without_instance_starts_selected_configuration(service_project, tmp_path):
    path = isolated_config(tmp_path / "source")
    upgrade_database(load_settings(path))
    assert command(service_project, "restart", path).returncode == 0
    assert command(service_project, "status").returncode == 0
    assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["missing-database", "occupied-port"])
def test_foreground_start_failure_releases_state(service_project, tmp_path, failure):
    path = isolated_config(tmp_path / "source")
    with socket.socket() as listener:
        if failure == "occupied-port":
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            data = read_config(path)
            data["server"]["port"] = listener.getsockname()[1]
            save_config(path, data)
            upgrade_database(load_settings(path))
        with foreground_service(path) as (child, output):
            assert child.wait(timeout=load_settings(path).testing.command_timeout_seconds) == 1
        assert not instance_active()
        assert not runtime_path("instance.json").exists()
        assert "Traceback" not in output.read_text()
        if failure == "occupied-port":
            assert listener.getsockname()[1] == load_settings(path).server.port


@pytest.mark.parametrize("interrupted", [True, False])
@pytest.mark.parametrize("cleanup_failure", ["timeout", "signal"])
def test_startup_cleanup_timeout_preserves_original_failure(
    service_project, tmp_path, monkeypatch, capsys, interrupted, cleanup_failure
):
    path = isolated_config(tmp_path / "source")
    signals = []

    class StalledChild:
        pid = 999999

        def poll(self):
            return None

        def send_signal(self, sig):
            signals.append(sig)
            if cleanup_failure == "signal":
                raise OSError("synthetic signal failure")

        def wait(self, *, timeout):
            raise subprocess.TimeoutExpired("synthetic-child", timeout)

    def cancel(_seconds):
        if interrupted:
            raise KeyboardInterrupt
        raise service_control.ServiceError("Startup timed out: synthetic original cause")

    monkeypatch.setattr(service_control.subprocess, "Popen", lambda *a, **kw: StalledChild())
    monkeypatch.setattr(service_control, "read_record", lambda: None)
    monkeypatch.setattr(service_control.time, "sleep", cancel)
    monkeypatch.setattr("sys.argv", ["service", "start", "--config", str(path)])
    if interrupted:
        assert service.main() == 130
    else:
        with pytest.raises(SystemExit) as error:
            service.main()
        assert error.value.code == 1
    stderr = capsys.readouterr().err
    assert (
        "Startup cleanup timed out" if cleanup_failure == "timeout" else "Startup cleanup failed"
    ) in stderr
    if not interrupted:
        assert "synthetic original cause" in stderr
    assert signals == [signal.SIGINT]


def test_health_probe_treats_invalid_http_as_unhealthy(monkeypatch):
    class InvalidHTTP:
        def open(self, *args, **kwargs):
            raise BadStatusLine("synthetic non-HTTP response")

    monkeypatch.setattr(service_control, "build_opener", lambda *args: InvalidHTTP())
    assert not is_healthy("http://127.0.0.1:1")


def test_uvicorn_startup_exit_is_normalized_and_cleans_up(tmp_path, monkeypatch, capsys):
    path = isolated_config(tmp_path / "source")
    closed = []
    control = SimpleNamespace(
        start=lambda: None,
        stopping=SimpleNamespace(set=lambda: None),
        close=lambda: closed.append(True),
    )

    def startup_failure(_server):
        raise SystemExit(3)

    monkeypatch.setattr(service, "create_app", lambda _: "unused")
    monkeypatch.setattr(service, "configure_logging", lambda _: None)
    monkeypatch.setattr(service, "InstanceControl", lambda *args: control)
    monkeypatch.setattr(uvicorn.Server, "run", startup_failure)
    monkeypatch.setattr("sys.argv", ["service", "run", "--config", str(path)])
    with pytest.raises(SystemExit) as error:
        service.main()
    assert error.value.code == 1
    assert "Application startup failed" in capsys.readouterr().err
    assert closed == [True]
    assert not instance_active()


def test_test_command_timeout_fails_without_force_kill(tmp_path, monkeypatch):
    signals = []

    class StalledCommand:
        pid = 999999

        def communicate(self, *, timeout):
            raise subprocess.TimeoutExpired("synthetic-command", timeout)

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: StalledCommand())
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(pytest.fail.Exception, match="retained without SIGKILL"):
        run_service_command(
            ["synthetic-command"], cwd=tmp_path, command_timeout=0.01, shutdown_timeout=0.01
        )
    assert signals == [(999999, signal.SIGINT)]


def test_service_fixture_uses_copied_migrations(service_project):
    settings = load_settings(service_project / "configs/app.toml")
    assert migration_config(settings).get_main_option("script_location") == str(
        service_project / "backend/migrations"
    )


@pytest.mark.integration
def test_service_fixture_stops_instance_when_test_body_fails(tmp_path, monkeypatch):
    with monkeypatch.context() as scope:
        with pytest.raises(RuntimeError, match="synthetic test failure"):
            with isolated_service_project(tmp_path / "nested", scope) as project:
                path = project / "configs/app.toml"
                data = read_config(path)
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    data["server"]["port"] = listener.getsockname()[1]
                save_config(path, data)
                upgrade_database(load_settings(path))
                assert command(project, "start", path).returncode == 0
                raise RuntimeError("synthetic test failure")
        assert not instance_active()
        assert not runtime_path("instance.json").exists()


def observed_wait_command(project, marker, action, path):
    code = f"""
from pathlib import Path
from entrypoints import service, service_control
original_sleep = service_control.time.sleep
def observe(seconds):
    if service_control.read_record() is not None:
        Path({str(marker)!r}).touch()
    original_sleep(seconds)
service_control.time.sleep = observe
raise SystemExit(service.main())
"""
    return subprocess.Popen(
        [str(project / "backend/.venv/bin/python"), "-c", code, action, "--config", str(path)],
        cwd=project / "backend",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


@pytest.mark.integration
def test_interrupt_during_startup_wait_reclaims_only_owned_child(service_project, tmp_path):
    path = isolated_config(tmp_path / "source")
    data = read_config(path)
    data["allowed_hosts"] = []  # 服务能启动，但父命令不能通过 HTTP 就绪检查。
    save_config(path, data)
    upgrade_database(load_settings(path))
    child = observed_wait_command(service_project, tmp_path / "waiting", "start", path)
    try:
        wait_for_marker(tmp_path / "waiting", child)
        assert read_record() is not None
        os.killpg(child.pid, signal.SIGINT)
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 130, stdout + stderr
        assert not instance_active()
        assert not runtime_path("instance.json").exists()
    finally:
        finish_child(child)


@pytest.mark.integration
@pytest.mark.parametrize("action", ["stop", "restart"])
def test_interrupt_during_stop_wait_preserves_instance(
    service_project, tmp_path, monkeypatch, action
):
    path = isolated_config(tmp_path / "source")
    settings = load_settings(path)
    signals = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    control = service_control.InstanceControl(
        settings, uvicorn.Server(uvicorn.Config("unused")), "synthetic-fingerprint"
    )
    child = None
    with service_lock(runtime_path("run.lock")):
        control.start()
        previous = runtime_path("instance.json").read_bytes()
        try:
            marker = tmp_path / "waiting"
            child = observed_wait_command(service_project, marker, action, path)
            wait_for_marker(marker, child)
            os.killpg(child.pid, signal.SIGINT)
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 130, stdout + stderr
            assert runtime_path("instance.json").read_bytes() == previous
            assert signals == [(os.getpid(), signal.SIGINT)]
            assert not runtime_path("console.log").exists()
        finally:
            finish_child(child)
            control.close()


def test_settings_without_loader_has_explicit_source_error(tmp_path):
    loaded = load_settings(isolated_config(tmp_path / "source"))
    plain = Settings.model_validate(loaded.model_dump())
    assert plain._source_file is None
    with pytest.raises(ValueError, match="explicit TOML document"):
        _ = plain.source_file
    assert loaded.source_file == loaded._source_file
    assert "source_file" not in loaded.model_dump()
    assert "source_file" not in Settings.model_json_schema()["properties"]


@pytest.mark.parametrize("name", ["run.lock", "control.lock", "instance.json"])
def test_lock_rejects_foreign_or_non_lock_paths(tmp_path, name):
    path = runtime_path(name) if name == "instance.json" else tmp_path / "foreign" / name
    with pytest.raises(ValueError, match="Service locks"):
        with service_lock(path):
            pytest.fail("An invalid lock path was accepted")
    assert not path.exists()
    assert not runtime_path("control.lock").exists()


@pytest.mark.integration
@pytest.mark.parametrize("action,expected", [("start", 0), ("run", 0), ("status", 1), ("stop", 1)])
def test_incomplete_registration_is_never_signalled_or_replaced(
    service_project, tmp_path, action, expected
):
    with service_lock(runtime_path("run.lock")):
        original_inode = runtime_path("run.lock").stat().st_ino
        result = command(service_project, action, tmp_path / "missing.toml")
        assert result.returncode == expected, result.stdout + result.stderr
        assert "registration" in result.stdout + result.stderr
        assert runtime_path("run.lock").stat().st_ino == original_inode
        assert not runtime_path("instance.json").exists()
        assert not runtime_path("console.log").exists()
        assert instance_active()


@pytest.mark.integration
def test_control_token_stays_in_private_records_not_snapshots_logs_or_arguments(
    service_project, tmp_path, monkeypatch, capsys
):
    path = isolated_config(tmp_path / "source")
    data = read_config(path)
    data["logging"]["console"] = True
    save_config(path, data)
    settings = load_settings(path)
    upgrade_database(settings)
    controller = ServiceController(config_file=path)
    original_popen = subprocess.Popen
    launches = []
    snapshots = []

    def observe_launch(arguments, **kwargs):
        if "--settings-fd" in arguments:
            descriptor = kwargs["pass_fds"][0]
            metadata = os.fstat(descriptor)
            assert metadata.st_nlink == 0
            snapshots.append(os.pread(descriptor, metadata.st_size, 0))
            launches.append(arguments)
        return original_popen(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", observe_launch)
    try:
        assert controller.execute("start") == 0
        record = read_record()
        assert record is not None
        token = record.token
        process_arguments = subprocess.run(
            ["ps", "-p", str(record.pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
        assert token not in process_arguments
        assert "--settings-fd" not in record.command
        assert launches and snapshots
        assert all(token not in " ".join(arguments) for arguments in launches)
        assert all(token.encode() not in snapshot for snapshot in snapshots)
        assert runtime_path("instance.json").stat().st_mode & 0o777 == 0o600
        assert controller.execute("stop") == 0
        captured = capsys.readouterr()
        assert token not in captured.out + captured.err
        assert token not in runtime_path("console.log").read_text()
        assert token not in (settings.logging.directory / settings.logging.filename).read_text()
    finally:
        controller.execute("stop")


@pytest.mark.integration
def test_atomic_instance_record_keeps_pending_credentials_private(tmp_path, monkeypatch):
    settings = load_settings(isolated_config(tmp_path / "source"))
    control = service_control.InstanceControl(
        settings, uvicorn.Server(uvicorn.Config("unused")), "synthetic-fingerprint"
    )
    original_replace = Path.replace
    observed = []

    def inspect_pending(path, target):
        if path == runtime_path("instance.json.pending"):
            assert path.stat().st_mode & 0o777 == 0o600
            assert json.loads(path.read_text())["token"] == control.record.token
            observed.append(True)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", inspect_pending)
    with service_lock(runtime_path("run.lock")):
        try:
            control.start()
            assert observed == [True]
            assert runtime_path("instance.json").stat().st_mode & 0o777 == 0o600
            assert not runtime_path("instance.json.pending").exists()
        finally:
            control.close()


def test_extra_private_storage_is_protected_by_shared_path_policy(service_project, tmp_path):
    settings = load_settings(isolated_config(tmp_path / "source"))
    extra = tmp_path / "synthetic-extra-private"
    with pytest.raises(ValueError, match="private data"):
        validate_runtime_paths(
            service_project,
            frontend_dir=extra / "public",
            frontend_clean_output=False,
            data_dir=settings.data_dir,
            backup_directory=settings.backup_directory,
            logging_directory=settings.logging.directory,
            temporary_directory=settings.testing.temporary_directory,
            database_filename=settings.database_filename,
            logging_filename=settings.logging.filename,
            extra_private_paths={"synthetic.storage": extra},
        )


@pytest.mark.parametrize("filename", ["instance.json", "instance.json.pending"])
@pytest.mark.parametrize("removal", ["after-exists", "before-lstat"])
def test_runtime_records_may_disappear_during_validation(
    service_project, monkeypatch, filename, removal
):
    directory = service_project / ".run"
    directory.mkdir()
    target = directory / filename
    target.write_text("{}")
    original_exists = Path.exists
    original_lstat = Path.lstat

    def exists_then_remove(path, *args, **kwargs):
        result = original_exists(path, *args, **kwargs)
        if path == target and result:
            path.unlink()
        return result

    def remove_before_lstat(path, *args, **kwargs):
        if path == target:
            path.unlink(missing_ok=True)
        return original_lstat(path, *args, **kwargs)

    if removal == "after-exists":
        monkeypatch.setattr(Path, "exists", exists_then_remove)
    else:
        monkeypatch.setattr(Path, "lstat", remove_before_lstat)
    assert runtime_path(filename) == target


@pytest.mark.parametrize("field", ["data_dir", "backup_directory", "logging.directory"])
def test_extra_private_paths_cannot_hide_builtin_storage(service_project, tmp_path, field):
    settings = load_settings(isolated_config(tmp_path / "source"))
    with pytest.raises(ValueError, match="must not override"):
        validate_runtime_paths(
            service_project,
            frontend_dir=settings.frontend_dir,
            frontend_clean_output=False,
            data_dir=settings.data_dir,
            backup_directory=settings.backup_directory,
            logging_directory=settings.logging.directory,
            temporary_directory=settings.testing.temporary_directory,
            database_filename=settings.database_filename,
            logging_filename=settings.logging.filename,
            extra_private_paths={field: tmp_path / "replacement"},
        )
