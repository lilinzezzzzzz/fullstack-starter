import os
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

import pytest

from app import config as app_config
from app.config import BACKEND_ROOT, Settings, load_settings
from entrypoints import service, service_control
from migrations import operations
from tests.helpers import read_config, save_config, write_config


@contextmanager
def isolated_service_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    project = tmp_path / "isolated project 中文"
    backend = project / "backend"
    backend.mkdir(parents=True)
    for name in ("app", "entrypoints", "migrations"):
        shutil.copytree(
            BACKEND_ROOT / name, backend / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ("pyproject.toml", "uv.lock", ".python-version", "alembic.ini"):
        shutil.copy2(BACKEND_ROOT / name, backend / name)
    shutil.copytree(BACKEND_ROOT.parent / "entrypoints", project / "entrypoints")
    (backend / ".venv").symlink_to(BACKEND_ROOT / ".venv", target_is_directory=True)
    overrides = {"security": {"api_token": ""}} if "security" in Settings.model_fields else {}
    default = write_config(tmp_path / "default settings", **overrides)
    data = read_config(default)
    data["server"].update(graceful_shutdown_seconds=0.1)
    data["service"].update(startup_timeout_seconds=5.0, stop_timeout_seconds=2.0)
    (project / "configs").mkdir()
    save_config(project / "configs/app.toml", data)
    monkeypatch.setattr(app_config, "PROJECT_ROOT", project)
    monkeypatch.setattr(service_control, "PROJECT_ROOT", project)
    monkeypatch.setattr(service_control, "BACKEND_ROOT", backend)
    monkeypatch.setattr(operations, "BACKEND_ROOT", backend)
    monkeypatch.setattr(service, "CONFIG_FILE", project / "configs/app.toml")
    try:
        yield project
    finally:
        directory = project / ".run"
        # 路径拒绝测试可以故意留下别名；绝不沿符号链接清理其目标。
        if directory.is_dir() and not directory.is_symlink():
            if service_control.instance_active():
                service_control.ServiceController().execute("stop")
            assert not service_control.instance_active(), (
                f"Active test instance retained: {project}"
            )


def run_service_command(
    arguments: list[str], *, cwd: Path, command_timeout: float, shutdown_timeout: float
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        arguments,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=command_timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.communicate(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"Test command timed out; PID {process.pid} retained without SIGKILL: {cwd}"
            )
        pytest.fail(f"Test command exceeded {command_timeout}s: {cwd}")
    return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


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
    settings = load_settings(config)
    output_file = config.with_suffix(".foreground.log")
    with output_file.open("w") as output:
        process = subprocess.Popen(
            command
            if command is not None
            else [
                "sh",
                str(service_control.PROJECT_ROOT / "entrypoints/service.sh"),
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
                    process.wait(timeout=settings.service.stop_timeout_seconds)
                except subprocess.TimeoutExpired:
                    pytest.fail(
                        f"Foreground shutdown timed out; PID {process.pid} retained "
                        f"without SIGKILL; diagnostics: {output_file}"
                    )


def wait_for_service(process: subprocess.Popen[bytes], settings: Settings, output: Path) -> str:
    base_url = f"http://127.0.0.1:{settings.server.port}"
    deadline = time.monotonic() + settings.service.startup_timeout_seconds
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
