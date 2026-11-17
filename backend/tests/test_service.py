import json
import os
import signal
import socket
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from app import config as app_config
from app.config import load_settings
from app.utils.database_lock import ServiceError, operation_lock
from migrations.operations import upgrade_database
from tests.helpers import read_config, response_trace_id, save_config, write_config
from tests.service_helpers import (
    command,
    configure_service,
    foreground_service,
    read_instance,
    unused_port,
    wait_for_service,
)


def test_database_lock_is_exclusive_and_released_after_failure(tmp_path: Path) -> None:
    database = tmp_path / "data/app.sqlite3"
    with pytest.raises(ValueError, match="probe"):
        with operation_lock(database):
            with pytest.raises(ServiceError):
                with operation_lock(database):
                    pytest.fail("The second operation acquired an active lock")
            raise ValueError("probe")
    with operation_lock(database):
        assert not database.exists()


@pytest.mark.integration
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("console", [False, True])
@pytest.mark.parametrize("group", [False, True])
def test_foreground_uses_native_uvicorn_signals_and_releases_application_resources(
    service_project, tmp_path, signum, console, group
):
    config = write_config(tmp_path / "configuration with spaces 中文")
    configure_service(service_project, port=unused_port(), graceful_shutdown_seconds=1)
    data = read_config(config)
    data["logging"]["console"] = console
    save_config(config, data)
    settings = load_settings(config)
    app_config.bind_settings(settings)
    upgrade_database()
    with foreground_service(config) as (process, output):
        base_url = wait_for_service(process, settings, output)
        record = json.loads((service_project / ".run/instance.json").read_text())
        assert record["pid"] == process.pid  # Shell 直接 exec 为 Uvicorn 进程。
        assert "started_at" in record
        assert not {"identity", "project", "uid", "command"} & record.keys()
        assert "token" not in record and "fingerprint" not in record
        with urlopen(
            Request(
                base_url + "/api/v1/hello",
                headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
            ),
            timeout=2,
        ) as response:
            assert json.load(response) == {"message": "Hello World"}
            assert response_trace_id(response.headers) == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert command(service_project, "status").returncode == 0
        if group:
            os.killpg(process.pid, signum)
        else:
            os.kill(process.pid, signum)
        assert process.wait(timeout=10) == (0 if signum == signal.SIGINT else -signal.SIGTERM)
    log = (settings.logging.directory / settings.logging.filename).read_text()
    console_output = output.read_text()
    for message in ("Started server process", "Waiting for application startup."):
        assert message in console_output
        assert message not in log
    assert "Application startup complete." in log
    assert "4bf92f3577b34da6a3ce929d0e0e4736 | GET /api/v1/hello 200" in log
    assert read_instance(service_project) is None
    assert not (service_project / ".run/run.lock").exists()
    upgrade_database()
    if console:
        assert "GET /api/v1/hello 200" in console_output


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["missing-database", "occupied-port", "missing-frontend"])
def test_startup_failures_do_not_change_database_or_other_listener(
    service_project, tmp_path, failure
):
    config = write_config(tmp_path / "failed startup")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1] if failure == "occupied-port" else unused_port()
        configure_service(service_project, port=port, graceful_shutdown_seconds=1)
        if failure != "missing-database":
            app_config.bind_settings(load_settings(config))
            upgrade_database()
        if failure == "missing-frontend":
            data = read_config(config)
            data["serve_frontend"] = True
            save_config(config, data)
        result = command(service_project, "start", "--config", str(config))
        assert result.returncode == 1, result.stdout + result.stderr
        assert listener.getsockname()[1] > 0
    assert read_instance(service_project) is None
    if failure == "missing-database":
        assert not load_settings(config).database_path.exists()
    with operation_lock(load_settings(config).database_path):
        pass


@pytest.mark.integration
def test_health_must_belong_to_the_registered_listener(service_project, tmp_path):
    config = write_config(tmp_path / "other health")
    settings = load_settings(config)
    app_config.bind_settings(settings)
    upgrade_database()
    configure_service(service_project, port=unused_port(), graceful_shutdown_seconds=1)
    with foreground_service(config) as (process, output):
        wait_for_service(process, settings, output)
        path = service_project / ".run/instance.json"
        original = path.read_text()
        altered = json.loads(original)
        altered["url"] = "http://127.0.0.1:1"
        try:
            path.write_text(json.dumps(altered))
            assert command(service_project, "status").returncode == 1
        finally:
            path.write_text(original)
        assert command(service_project, "stop").returncode == 0
        assert process.wait(timeout=8) == 0


@pytest.mark.integration
def test_foreground_run_preserves_uvicorn_startup_failure_exit_code(service_project, tmp_path):
    config = write_config(tmp_path / "native startup failure")
    configure_service(service_project, port=unused_port(), graceful_shutdown_seconds=1)
    with foreground_service(config) as (process, output):
        assert process.wait(timeout=10) == 3, output.read_text()
    assert read_instance(service_project) is None


@pytest.mark.integration
def test_database_maintenance_lock_remains_without_service_run_lock(service_project):
    config = service_project / "configs/app.toml"
    settings = load_settings(config)
    upgrade_database()
    result = command(service_project, "start")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (service_project / ".run/run.lock").exists()
    with pytest.raises(ServiceError):
        with operation_lock(settings.database_path):
            pytest.fail("Running service did not retain the database maintenance lock")
    assert command(service_project, "stop").returncode == 0
    with operation_lock(settings.database_path):
        pass
