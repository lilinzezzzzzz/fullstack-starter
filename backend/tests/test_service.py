import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from app.config import PROJECT_ROOT, Settings, load_settings
from app.service_state import ServiceError, operation_lock
from migrations.operations import upgrade_database
from tests.helpers import read_config, response_trace_id, save_config, write_config


def test_database_lock_is_exclusive_and_released_after_failure(tmp_path: Path) -> None:
    database = tmp_path / "data/app.sqlite3"
    with pytest.raises(ValueError, match="probe"):
        with operation_lock(database):
            with pytest.raises(ServiceError, match="in progress"):
                with operation_lock(database):
                    pytest.fail("The second operation acquired an active lock")
            raise ValueError("probe")
    with operation_lock(database):
        assert not database.exists()


def unused_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


@contextmanager
def foreground_service(
    config: Path,
) -> Generator[tuple[subprocess.Popen[bytes], Path]]:
    output_file = config.with_suffix(".foreground.log")
    with output_file.open("w") as output:
        process = subprocess.Popen(
            ["sh", str(PROJECT_ROOT / "entrypoints/service.sh"), "--config", str(config)],
            cwd=config.parent,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process, output_file
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)


def wait_for_service(process: subprocess.Popen[bytes], settings: Settings, output: Path) -> str:
    base_url = f"http://127.0.0.1:{settings.server.port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(output.read_text())
        try:
            with urlopen(f"{base_url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return base_url
        except OSError:
            time.sleep(0.05)
    pytest.fail(f"Service did not become ready: {output.read_text()}")


@pytest.mark.integration
def test_foreground_service_ctrl_c_and_maintenance_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path / "configuration with spaces")
    data = read_config(config)
    data["server"]["port"] = unused_port()
    data["server"]["graceful_shutdown_seconds"] = 1
    data["logging"]["console"] = True
    save_config(config, data)
    settings = load_settings(config)
    upgrade_database(settings)
    monkeypatch.setenv("OTEL_PROPAGATORS", "not-installed-propagator")
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    with foreground_service(config) as (process, output):
        base_url = wait_for_service(process, settings, output)
        with urlopen(
            Request(
                f"{base_url}/api/v1/hello",
                headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
            ),
            timeout=3,
        ) as response:
            assert json.load(response) == {"message": "Hello World"}
            assert response_trace_id(response.headers) == "4bf92f3577b34da6a3ce929d0e0e4736"
        migration = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(PROJECT_ROOT / "backend"),
                "python",
                "-m",
                "app.cli",
                "--config",
                str(config),
                "db-upgrade",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert migration.returncode != 0
        assert "in progress" in migration.stderr
        second = config.parent / "second.toml"
        data["server"]["port"] = unused_port()
        save_config(second, data)
        with foreground_service(second) as (duplicate, duplicate_output):
            assert duplicate.wait(timeout=10) != 0
            assert "in progress" in duplicate_output.read_text()
        assert process.poll() is None
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=10)
    assert "Application shutdown complete" in output.read_text()
    assert not list(tmp_path.rglob("*.pid"))
    upgrade_database(settings)


@pytest.mark.integration
def test_failed_start_does_not_create_or_upgrade_database(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config)
    with foreground_service(config) as (process, _output):
        assert process.wait(timeout=10) != 0
    log = settings.logging.directory / settings.logging.filename
    assert "Database missing" in log.read_text()
    assert not settings.database_path.exists()
    with operation_lock(settings.database_path):
        pass


@pytest.mark.integration
def test_occupied_port_is_left_untouched_and_database_lock_is_released(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        config = write_config(tmp_path)
        data = read_config(config)
        data["server"]["port"] = listener.getsockname()[1]
        save_config(config, data)
        settings = load_settings(config)
        upgrade_database(settings)
        with foreground_service(config) as (process, _output):
            assert process.wait(timeout=10) != 0
        assert listener.getsockname()[1] == settings.server.port
        upgrade_database(settings)
