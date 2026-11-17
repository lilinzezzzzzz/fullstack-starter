import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from textwrap import indent
from urllib.request import urlopen

import pytest

from app import config as app_config
from app.config import BACKEND_ROOT, Settings
from app.infra import database
from migrations import operations
from tests.helpers import read_config, save_config, write_config

SERVICE_PROJECT: Path | None = None


def require_service_project() -> Path:
    if SERVICE_PROJECT is None:
        raise RuntimeError("Service tests require an isolated project fixture")
    return SERVICE_PROJECT


def configure_service(project: Path, **overrides: object) -> Path:
    path = project / "entrypoints/service.sh"
    script = path.read_text()
    fields = {
        "host": "server_host",
        "port": "server_port",
        "graceful_shutdown_seconds": "graceful_shutdown_seconds",
    }
    for field, value in overrides.items():
        script, count = re.subn(
            rf"^{fields[field]}=.*$",
            f"{fields[field]}={value}",
            script,
            count=1,
            flags=re.MULTILINE,
        )
        assert count == 1
    path.write_text(script)
    return path


def insert_before_lifespan_yield(project: Path, code: str) -> None:
    """向临时启动入口插入探针，保留实际缩进并在写入前校验语法。"""
    path = project / "backend/app/application.py"
    source, count = re.subn(
        r"^([ ]*)yield$",
        lambda match: indent(code.rstrip() + "\n", match[1]) + match[0],
        path.read_text(),
        flags=re.MULTILINE,
    )
    assert count == 1, "Expected exactly one lifespan yield"
    compile(source, str(path), "exec")
    path.write_text(source)


def service_port(project: Path) -> int:
    return int(
        re.search(
            r"^server_port=([0-9]+)$",
            (project / "entrypoints/service.sh").read_text(),
            re.MULTILINE,
        )[1]
    )


def process_started_at(pid: int) -> str | None:
    response = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "stat="],
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        check=False,
    )
    fields = response.stdout.split()
    if response.returncode or len(fields) != 6 or fields[-1].startswith("Z"):
        return None
    return " ".join(fields[:5])


def read_instance(project: Path) -> dict | None:
    path = project / ".run/instance.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    return record if process_started_at(record["pid"]) == record["started_at"] else None


def write_instance(project: Path, pid: int, *, timeout: float = 0.2) -> dict:
    record = {
        "format": 3,
        "pid": pid,
        "started_at": process_started_at(pid),
        "config": "/synthetic.toml",
        "url": "http://127.0.0.1:1",
        "log": "/synthetic.log",
        "stop_timeout": timeout,
    }
    path = project / ".run/instance.json"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    return record


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
    default = write_config(tmp_path / "default settings")
    data = read_config(default)
    data["service"].update(startup_timeout_seconds=8.0, stop_timeout_seconds=4.0)
    (project / "configs").mkdir()
    save_config(project / "configs/app.toml", data)
    configure_service(project, port=unused_port(), graceful_shutdown_seconds=1)
    monkeypatch.setattr(app_config, "PROJECT_ROOT", project)
    monkeypatch.setattr(database, "PROJECT_ROOT", project)
    monkeypatch.setitem(globals(), "SERVICE_PROJECT", project)
    monkeypatch.setattr(operations, "BACKEND_ROOT", backend)
    app_config.bind_settings(app_config.load_settings(project / "configs/app.toml"))
    try:
        yield project
    finally:
        directory = project / ".run"
        if directory.is_dir() and not directory.is_symlink():
            if read_instance(project) is not None:
                command(project, "stop")
            assert read_instance(project) is None, f"Active test instance retained: {project}"


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


def command(project: Path, action: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run_service_command(
        ["sh", str(project / "entrypoints/service.sh"), action, *arguments],
        cwd=project.parent,
        command_timeout=30,
        shutdown_timeout=8,
    )


def unused_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


@contextmanager
def foreground_service(
    config: Path, *, command: list[str] | None = None
) -> Generator[tuple[subprocess.Popen[bytes], Path]]:
    output_file = config.with_suffix(".foreground.log")
    with output_file.open("w") as output:
        process = subprocess.Popen(
            command
            if command is not None
            else [
                "sh",
                str(require_service_project() / "entrypoints/service.sh"),
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
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    pytest.fail(
                        f"Foreground shutdown timed out; PID {process.pid} retained; "
                        f"diagnostics: {output_file}"
                    )


def wait_for_service(process: subprocess.Popen[bytes], settings: Settings, output: Path) -> str:
    base_url = f"http://127.0.0.1:{service_port(require_service_project())}"
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
