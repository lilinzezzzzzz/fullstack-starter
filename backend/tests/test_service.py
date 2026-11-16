import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from app.config import PROJECT_ROOT, Settings, load_settings
from app.utils.database_lock import ServiceError, operation_lock
from entrypoints import service_control
from migrations.operations import upgrade_database
from tests.helpers import read_config, response_trace_id, save_config, write_config

pytestmark = pytest.mark.usefixtures("service_project")


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
    *,
    command: list[str] | None = None,
) -> Generator[tuple[subprocess.Popen[bytes], Path]]:
    output_file = config.with_suffix(".foreground.log")
    with output_file.open("w") as output:
        process = subprocess.Popen(
            command
            if command is not None
            else [
                "sh",
                str(service_control.PROJECT_ROOT / "backend/entrypoints/service.sh"),
                "run",
                "--config",
                str(config),
            ],
            cwd=config.parent,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process, output_file
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
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
@pytest.mark.parametrize("console", [False, True], ids=["file", "file-and-console"])
def test_foreground_service_ctrl_c_and_maintenance_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, console: bool
) -> None:
    config = write_config(tmp_path / "configuration with spaces")
    data = read_config(config)
    data["server"]["port"] = unused_port()
    data["server"]["graceful_shutdown_seconds"] = 1
    data["logging"]["console"] = console
    save_config(config, data)
    settings = load_settings(config)
    upgrade_database(settings)
    monkeypatch.setenv("OTEL_PROPAGATORS", "not-installed-propagator")
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    with foreground_service(config) as (process, output):
        base_url = wait_for_service(process, settings, output)
        record = json.loads(service_control.runtime_path("instance.json").read_text())
        assert record["pid"] == process.pid
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
                "entrypoints.cli",
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
        data["logging"]["console"] = True
        save_config(second, data)
        with foreground_service(second) as (duplicate, duplicate_output):
            assert duplicate.wait(timeout=10) != 0
            assert "in progress" in duplicate_output.read_text()
        assert process.poll() is None
        os.killpg(process.pid, signal.SIGINT)
        assert process.wait(timeout=10) == 0
    terminal = output.read_text()
    assert "resource_tracker" not in terminal
    assert "leaked semaphore" not in terminal
    if console:
        assert "Application shutdown complete" in terminal
        assert "Finished server process" in terminal
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert "4bf92f3577b34da6a3ce929d0e0e4736 | GET /api/v1/hello 200" in contents
    assert "Application shutdown complete" in contents
    assert "Finished server process" in contents
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


@pytest.mark.integration
def test_repeated_sigint_cannot_interrupt_final_control_cleanup(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    data = read_config(config)
    data["server"]["port"] = unused_port()
    save_config(config, data)
    settings = load_settings(config)
    upgrade_database(settings)
    marker = config.with_suffix(".cleanup")
    # 在独立解释器中放大关闭窗口，确定第二个信号落在 Uvicorn 退出之后。
    probe = tmp_path / "cleanup_probe.py"
    probe.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from entrypoints import service\n"
        "original_close = service.InstanceControl.close\n"
        "def delayed_close(self):\n"
        "    Path(sys.argv[-1]).with_suffix('.cleanup').touch()\n"
        "    time.sleep(0.5)\n"
        "    original_close(self)\n"
        "service.InstanceControl.close = delayed_close\n"
        "service.main()\n"
    )
    command = [sys.executable, "-c", probe.read_text(), "run", "--config", str(config)]
    # -c 从 backend 加载包；测试资源及日志仍全部位于 tmp_path。
    backend = service_control.PROJECT_ROOT / "backend"
    command[2] = f"import sys; sys.path.insert(0, {str(backend)!r})\n" + command[2]
    with foreground_service(config, command=command) as (process, output):
        wait_for_service(process, settings, output)
        os.killpg(process.pid, signal.SIGINT)
        deadline = time.monotonic() + 5
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), output.read_text()
        os.killpg(process.pid, signal.SIGINT)
        assert process.wait(timeout=5) == 0
    assert "Traceback" not in output.read_text()
    assert not service_control.runtime_path("instance.json").exists()
    upgrade_database(settings)
