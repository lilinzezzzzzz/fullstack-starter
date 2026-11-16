"""项目单实例控制：认证回环通道、受保护的运行文件与不可变配置快照。"""

import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Literal
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

import uvicorn
from pydantic import BaseModel, ConfigDict, Field

from app.config import (
    BACKEND_ROOT,
    CONFIG_FILE,
    PROJECT_ROOT,
    Settings,
    load_settings_snapshot,
    settings_from_document,
)
from app.utils.database_lock import ServiceError

# 固定的控制协议预算；应用启动和停止期限来自显式 TOML。
CONTROL_TIMEOUT_SECONDS = 0.5
HEALTH_TIMEOUT_SECONDS = 1.0
COMMAND_LOCK_TIMEOUT_SECONDS = 40
POLL_INTERVAL_SECONDS = 0.05
MESSAGE_LIMIT = 4096


class InstanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocol: Literal[1]
    pid: int = Field(gt=0)
    started_at: datetime
    command: list[str] = Field(min_length=1)
    port: int = Field(gt=0, le=65535)
    token: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    project: str
    config: str
    fingerprint: str
    url: str
    log: str
    shutdown_timeout: float = Field(gt=0, allow_inf_nan=False)


class InstanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    pid: int = Field(gt=0)
    fingerprint: str
    phase: Literal["starting", "running", "stopping"]


class StartupSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    config: str
    document: str = Field(repr=False)


def runtime_path(filename: str) -> Path:
    filenames = {
        "instance.json",
        "instance.json.pending",
        "run.lock",
        "control.lock",
        "console.log",
    }
    if filename not in filenames:
        raise ValueError("Unknown service runtime file")
    directory = PROJECT_ROOT / ".run"
    try:
        directory_mode = directory.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISDIR(directory_mode):
            raise ServiceError("Service runtime directory .run must be a real directory")
    for name in filenames:
        path = directory / name
        # 登记和退出会替换或删除记录；同一条目只读取一次元数据。
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise ServiceError(f"Service runtime file {name} must be a regular file")
    return directory / filename


@contextmanager
def service_lock(path: Path, timeout: float = 0) -> Generator[None]:
    if path.name not in {"run.lock", "control.lock"} or path != runtime_path(path.name):
        raise ValueError("Service locks must use the project's run.lock or control.lock path")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as handle:
        os.fchmod(handle.fileno(), 0o600)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ServiceError(
                        "Another service command or instance is in progress."
                    ) from exc
                time.sleep(POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def instance_active() -> bool:
    path = runtime_path("run.lock")
    try:
        with service_lock(path):
            return False
    except ServiceError as exc:
        # 路径错误不能被误认为有实例；只捕获确实被占用的 flock。
        if isinstance(exc.__cause__, BlockingIOError):
            return True
        raise


def read_record() -> InstanceRecord | None:
    path = runtime_path("instance.json")
    if not instance_active():
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as source:
        if stat.S_IMODE(os.fstat(source.fileno()).st_mode) & 0o077:
            raise ServiceError("Instance credentials must have private permissions; no signal sent")
        try:
            record = InstanceRecord.model_validate_json(source.read())
        except ValueError as exc:
            raise ServiceError("Invalid or obsolete instance state; no signal sent") from exc
    if record.project != str(PROJECT_ROOT):
        raise ServiceError(
            f"Instance belongs to a different project ({record.project}); "
            "stop it using the original project path and version; no signal sent"
        )
    return record


def service_url(settings: Settings) -> str:
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(settings.server.host, settings.server.host)
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{settings.server.port}"


def is_healthy(url: str, timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    try:
        request = Request(url + "/api/health", headers={"Connection": "close"})
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            return response.status == 200 and json.load(response) == {
                "status": "ok",
                "database": "ok",
            }
    except URLError, OSError, ValueError, HTTPException:
        return False


def read_startup_snapshot(descriptor: int) -> tuple[Settings, bytes]:
    with os.fdopen(descriptor, "rb") as source:
        payload = source.read()
    try:
        snapshot = StartupSnapshot.model_validate_json(payload)
        config = Path(snapshot.config)
        settings = settings_from_document(snapshot.document.encode("utf-8"), config)
    except ValueError as exc:
        raise ServiceError("Invalid startup snapshot") from exc
    return settings, payload


def receive_message(connection: socket.socket) -> bytes:
    with connection.makefile("rb") as source:
        message = source.readline(MESSAGE_LIMIT + 1)
    if len(message) > MESSAGE_LIMIT or not message.endswith(b"\n"):
        raise ValueError("Invalid service control message")
    return message


def exchange(record: InstanceRecord, command: Literal["status", "stop"]) -> InstanceStatus:
    with socket.create_connection(
        ("127.0.0.1", record.port), CONTROL_TIMEOUT_SECONDS
    ) as connection:
        connection.settimeout(CONTROL_TIMEOUT_SECONDS)
        connection.sendall(
            json.dumps(
                {
                    "token": record.token,
                    "pid": record.pid,
                    "fingerprint": record.fingerprint,
                    "command": command,
                }
            ).encode()
            + b"\n"
        )
        result = InstanceStatus.model_validate_json(receive_message(connection))
    if result.pid != record.pid or result.fingerprint != record.fingerprint:
        raise ServiceError("Instance identity mismatch; no further action taken")
    return result


class InstanceControl:
    def __init__(self, settings: Settings, server: uvicorn.Server, fingerprint: str) -> None:
        self.settings = settings
        self.server = server
        self.fingerprint = fingerprint
        self.closed = threading.Event()
        self.stopping = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.thread = threading.Thread(target=self._listen, name="service-control", daemon=True)
        self.record: InstanceRecord | None = None

    def start(self) -> None:
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.listener.settimeout(POLL_INTERVAL_SECONDS)
        self.record = InstanceRecord(
            protocol=1,
            pid=os.getpid(),
            started_at=datetime.now(UTC),
            command=[
                sys.executable,
                "-m",
                "entrypoints.service",
                "run",
                "--config",
                str(self.settings.source_file),
            ],
            port=self.listener.getsockname()[1],
            token=secrets.token_hex(32),
            project=str(PROJECT_ROOT),
            config=str(self.settings.source_file),
            fingerprint=self.fingerprint,
            url=service_url(self.settings),
            log=str(self.settings.logging.directory / self.settings.logging.filename),
            shutdown_timeout=self.settings.service.stop_timeout_seconds,
        )
        pending = runtime_path("instance.json.pending")
        pending.unlink(missing_ok=True)
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(self.record.model_dump_json())
        pending.replace(runtime_path("instance.json"))
        self.thread.start()

    def close(self) -> None:
        self.closed.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=CONTROL_TIMEOUT_SECONDS + 2 * POLL_INTERVAL_SECONDS)
        self.listener.close()
        if self.record is not None:
            runtime_path("instance.json").unlink(missing_ok=True)

    def _listen(self) -> None:
        while not self.closed.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(CONTROL_TIMEOUT_SECONDS)
                try:
                    self._respond(connection)
                except OSError, ValueError:
                    continue

    def _respond(self, connection: socket.socket) -> None:
        request = json.loads(receive_message(connection))
        record = self.record
        if record is None or not isinstance(request, dict):
            return
        token = request.get("token")
        if not isinstance(token, str) or not secrets.compare_digest(
            token.encode(), record.token.encode()
        ):
            return
        if request.get("pid") != record.pid or request.get("fingerprint") != record.fingerprint:
            return
        command = request.get("command")
        if command not in ("status", "stop"):
            return
        should_signal = (
            command == "stop" and not self.stopping.is_set() and not self.server.should_exit
        )
        if command == "stop":
            self.stopping.set()
        phase = "running" if self.server.started else "starting"
        if self.stopping.is_set() or self.server.should_exit:
            phase = "stopping"
        result = InstanceStatus(pid=record.pid, fingerprint=record.fingerprint, phase=phase)
        try:
            connection.sendall(result.model_dump_json().encode() + b"\n")
        finally:
            if should_signal:
                os.kill(os.getpid(), signal.SIGINT)


class ServiceController:
    def __init__(self, *, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file
        self.settings: Settings | None = None
        self._snapshot: bytes | None = None
        self.directory = PROJECT_ROOT / ".run"

    def startup_settings(self) -> Settings:
        if self.settings is None:
            settings, document = load_settings_snapshot(self.config_file)
            self._snapshot = (
                StartupSnapshot(config=str(settings.source_file), document=document.decode("utf-8"))
                .model_dump_json()
                .encode()
            )
            self.settings = settings
        return self.settings

    def startup_snapshot(self) -> bytes:
        self.startup_settings()
        if self._snapshot is None:
            raise ServiceError("Startup snapshot is unavailable")
        return self._snapshot

    def restore_snapshot(self, descriptor: int) -> None:
        self.settings, self._snapshot = read_startup_snapshot(descriptor)

    def describe(self, record: InstanceRecord, message: str) -> None:
        print(f"{message}: PID {record.pid}; {record.url}/")
        print(f"Config: {record.config}\nLog: {record.log}")
        print(f"Background console (background runs only): {runtime_path('console.log')}")

    def report_existing(self) -> bool:
        record = read_record()
        if record is not None:
            try:
                exchange(record, "status")
            except (OSError, ValueError, ServiceError) as exc:
                raise ServiceError(
                    "Control channel unavailable; instance retained, no signal sent"
                ) from exc
            self.describe(record, "Service is already running")
            return True
        if instance_active():
            print("Service is already running: instance registration is in progress")
            return True
        return False

    def status(self) -> int:
        record = read_record()
        if record is None:
            if instance_active():
                print("starting: instance registration is in progress")
                return 1
            print("stopped")
            return 3
        try:
            state = exchange(record, "status")
        except OSError, ValueError, ServiceError:
            print(f"unreachable: PID {record.pid}; instance retained, no signal sent")
            return 1
        phase = state.phase
        if phase == "running":
            phase = "healthy" if is_healthy(record.url) else "unhealthy"
        self.describe(record, phase)
        return 0 if phase == "healthy" else 1

    def stop(self) -> int:
        record = read_record()
        if record is None:
            if instance_active():
                raise ServiceError("Instance registration is incomplete; no signal sent")
            print("already stopped")
            return 0
        try:
            exchange(record, "stop")
        except (OSError, ValueError, ServiceError) as exc:
            if instance_active():
                raise ServiceError(
                    "Control channel unavailable; instance retained, no signal sent"
                ) from exc
        deadline = time.monotonic() + record.shutdown_timeout
        while instance_active():
            if time.monotonic() >= deadline:
                raise ServiceError(
                    "Stop timed out; instance retained, no force kill or restart performed"
                )
            time.sleep(POLL_INTERVAL_SECONDS)
        print("stopped")
        return 0

    def start(self) -> int:
        if self.report_existing():
            return 0
        settings = self.startup_settings()
        payload = self.startup_snapshot()
        fingerprint = hashlib.sha256(payload).hexdigest()
        with service_lock(runtime_path("run.lock")):
            runtime_path("instance.json").unlink(missing_ok=True)
        output_path = runtime_path("console.log")
        log_path = settings.logging.directory / settings.logging.filename
        process: subprocess.Popen[bytes] | None = None
        ready = False
        try:
            with tempfile.TemporaryFile(dir=self.directory) as snapshot:
                snapshot.write(payload)
                snapshot.seek(0)
                descriptor = os.open(
                    output_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(descriptor, "ab") as output:
                    os.fchmod(output.fileno(), 0o600)
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "entrypoints.service",
                            "run",
                            "--config",
                            str(settings.source_file),
                            "--settings-fd",
                            str(snapshot.fileno()),
                        ],
                        pass_fds=(snapshot.fileno(),),
                        cwd=BACKEND_ROOT,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
            deadline = time.monotonic() + settings.service.startup_timeout_seconds
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ServiceError(
                        f"Service exited during startup; inspect {output_path} and {log_path}"
                    )
                record = read_record()
                if (
                    record is not None
                    and record.pid == process.pid
                    and record.fingerprint == fingerprint
                ):
                    try:
                        state = exchange(record, "status")
                    except OSError, ValueError, ServiceError:
                        state = None
                    remaining = max(0.01, deadline - time.monotonic())
                    if (
                        state is not None
                        and state.phase == "running"
                        and is_healthy(record.url, min(HEALTH_TIMEOUT_SECONDS, remaining))
                    ):
                        self.describe(record, "started")
                        ready = True
                        return 0
                time.sleep(POLL_INTERVAL_SECONDS)
            raise ServiceError(f"Startup timed out; inspect {output_path} and {log_path}")
        finally:
            pending_error = sys.exception()
            if not ready and process is not None:
                previous_signals = {
                    signum: signal.signal(signum, signal.SIG_IGN)
                    for signum in (signal.SIGINT, signal.SIGTERM)
                }
                try:
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        process.wait(timeout=settings.service.stop_timeout_seconds)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    reason = "timed out" if isinstance(exc, subprocess.TimeoutExpired) else "failed"
                    message = (
                        f"Startup cleanup {reason}; instance retained, no force kill performed"
                    )
                    if pending_error is None:
                        raise ServiceError(message) from exc
                    # 保留在途异常，尤其是决定退出码 130 的 KeyboardInterrupt。
                    print(message, file=sys.stderr)
                finally:
                    for signum, handler in previous_signals.items():
                        signal.signal(signum, handler)

    def execute(self, action: str) -> int:
        with service_lock(runtime_path("control.lock"), COMMAND_LOCK_TIMEOUT_SECONDS):
            if action == "status":
                return self.status()
            if action == "stop":
                return self.stop()
            if action == "restart":
                self.startup_snapshot()
                self.stop()
            return self.start()
