import json
import signal
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

import pytest

from app.config import PROJECT_ROOT, load_settings
from app.database import upgrade_database
from tests.helpers import read_config, save_config, write_config
from tools import service_control


def test_invalid_pid_is_never_used(tmp_path: Path) -> None:
    pid_file = tmp_path / "service.pid"
    for value in ("", "-1", "0", "1", "not-a-pid", "123\n456"):
        pid_file.write_text(value)
        with pytest.raises(service_control.ServiceError, match="Invalid PID"):
            service_control.read_pid(pid_file)
        assert pid_file.read_text() == value


@pytest.mark.parametrize(
    "command",
    [
        "S /usr/bin/other-service\n",
        "S /usr/bin/python -m tools.service_control run --ready-fd 3 --config {config}.other\n",
    ],
)
def test_foreign_pid_is_not_signalled_or_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    settings.service.pid_file.write_text("12345\n")
    signals = []
    monkeypatch.setattr(service_control.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(
        service_control.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            command.format(config=config),
            "",
        ),
    )
    with pytest.raises(service_control.ServiceError, match="not this service"):
        service_control.stop_service(settings, config)
    assert signals == [(12345, 0)]
    assert settings.service.pid_file.read_text() == "12345\n"


def test_process_inspection_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    settings.service.pid_file.write_text("12345\n")
    signals = []
    monkeypatch.setattr(service_control.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(
        service_control.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "permission denied"),
    )
    with pytest.raises(service_control.ServiceError, match="Cannot verify"):
        service_control.stop_service(settings, config)
    assert signals == [(12345, 0)]
    assert settings.service.pid_file.exists()


def test_stop_timeout_preserves_pid_without_force_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    settings.service.shutdown_timeout_seconds = 0.01
    settings.service.pid_file.write_text("12345\n")
    signals = []
    monkeypatch.setattr(service_control, "is_owned_process", lambda *args: True)
    monkeypatch.setattr(service_control, "process_info", lambda *args: ("S", "owned-service"))
    monkeypatch.setattr(service_control.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(service_control.ServiceError, match="No SIGKILL"):
        service_control.stop_service(settings, config)
    assert signals == [(12345, signal.SIGTERM)]
    assert settings.service.pid_file.exists()


def test_operation_lock_prevents_concurrent_controllers(tmp_path: Path) -> None:
    path = tmp_path / "service.pid"
    with service_control.operation_lock(path):
        with pytest.raises(service_control.ServiceError, match="in progress"):
            with service_control.operation_lock(path):
                pass


def test_stop_tolerates_argv_disappearing_during_normal_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    settings.service.pid_file.write_text("12345\n")
    signals = []
    states = iter([("E", "(python3.14)"), None])
    monkeypatch.setattr(service_control, "is_owned_process", lambda *args: True)
    monkeypatch.setattr(service_control, "process_info", lambda *args: next(states))
    monkeypatch.setattr(service_control.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    service_control.stop_service(settings, config)
    assert signals == [(12345, signal.SIGTERM)]
    assert not settings.service.pid_file.exists()


def unused_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def controller(config: Path, action: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["sh", str(PROJECT_ROOT / "scripts/service.sh"), action, "--config", str(config)],
        cwd=config.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return result


@pytest.mark.integration
def test_shell_start_status_restart_stop_and_stale_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path / "configuration with spaces")
    data = read_config(config)
    data["server"]["port"] = unused_port()
    data["server"]["graceful_shutdown_seconds"] = 1
    data["service"]["shutdown_timeout_seconds"] = 5
    save_config(config, data)
    settings = load_settings(config)
    upgrade_database(settings)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "must-not-be-used"))
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    monkeypatch.setenv("LOGURU_LEVEL", "ERROR")
    try:
        controller(config, "start")
        first_pid = service_control.read_pid(settings.service.pid_file)
        assert first_pid is not None
        info = service_control.process_info(first_pid, settings.service.inspection_timeout_seconds)
        assert info is not None
        assert " -m tools.service_control run " in info[1]
        assert "Running" in controller(config, "status").stdout
        assert "Already running" in controller(config, "start").stdout
        assert service_control.read_pid(settings.service.pid_file) == first_pid
        with urlopen(
            f"http://127.0.0.1:{settings.server.port}/api/v1/hello", timeout=3
        ) as response:
            assert json.load(response) == {"message": f"Hello, {settings.application.title}!"}
        controller(config, "restart")
        assert service_control.read_pid(settings.service.pid_file) != first_pid
        controller(config, "stop")
        assert not settings.service.pid_file.exists()
        controller(config, "status", expected=3)
        controller(config, "stop")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=3)
        settings.service.pid_file.write_text(f"{dead.pid}\n")
        controller(config, "start")
        assert service_control.read_pid(settings.service.pid_file) != dead.pid
    finally:
        controller(config, "stop")
    assert not settings.service.pid_file.exists()
    assert not (tmp_path / "must-not-be-used").exists()
    log = (settings.logging.directory / settings.logging.filename).read_text()
    assert "GET /api/v1/hello 200" in log
    assert "Application shutdown complete" in log
    assert settings.server.workers == 1


@pytest.mark.integration
def test_failed_start_does_not_record_running_pid(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    controller(config, "start", expected=1)
    assert not settings.service.pid_file.exists()
    assert not settings.database_path.exists()
    assert (
        "Database missing" in (settings.logging.directory / settings.logging.filename).read_text()
    )


@pytest.mark.integration
def test_occupied_port_is_not_adopted_or_stopped(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        config = write_config(tmp_path)
        data = read_config(config)
        data["server"]["port"] = listener.getsockname()[1]
        save_config(config, data)
        settings = load_settings(config)
        upgrade_database(settings)
        controller(config, "start", expected=1)
        assert not settings.service.pid_file.exists()
        assert listener.getsockname()[1] == settings.server.port
