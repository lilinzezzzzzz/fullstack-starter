"""本机实例登记与控制；只让经过实例凭据验证的目标进程向自身发送信号。"""

import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import uvicorn
from pydantic import BaseModel, ConfigDict, Field

from app.config import PROJECT_ROOT, Settings
from app.utils.database_lock import ServiceError

# 固定的本地控制协议边界，不是应用配置的回退值。
CONTROL_TIMEOUT_SECONDS = 0.5
POLL_INTERVAL_SECONDS = 0.1
MESSAGE_LIMIT = 4096


class InstanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    pid: int = Field(gt=0)
    started_at: datetime
    command: list[str] = Field(min_length=1)
    port: int = Field(gt=0, le=65535)
    token: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    project: str
    config: str
    fingerprint: str


class InstanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    pid: int = Field(gt=0)
    fingerprint: str
    phase: Literal["starting", "running", "stopping"]


def runtime_path(
    filename: Literal[
        "instance.json", "instance.json.pending", "run.lock", "control.lock", "console.log"
    ],
) -> Path:
    return PROJECT_ROOT / ".run" / filename


def settings_fingerprint(settings: Settings) -> str:
    contents = json.dumps(settings.model_dump(mode="json"), sort_keys=True).encode()
    return hashlib.sha256(contents).hexdigest()


@contextmanager
def service_lock(path: Path) -> Generator[None]:
    """锁文件保留在磁盘，避免删除后出现两个独立锁 inode。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ServiceError("Another service command or instance is in progress.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def instance_active() -> bool:
    try:
        with service_lock(runtime_path("run.lock")):
            return False
    except ServiceError:
        return True


def read_record(config: Path) -> InstanceRecord | None:
    if not instance_active():
        return None
    try:
        record = InstanceRecord.model_validate_json(runtime_path("instance.json").read_bytes())
    except FileNotFoundError:
        return None
    except ValueError as exc:
        raise ServiceError("Invalid instance state; refusing to control the process.") from exc
    if record.project != str(PROJECT_ROOT) or record.config != str(config):
        raise ServiceError("The service is managed by a different project or configuration file.")
    return record


def receive_message(connection: socket.socket) -> bytes:
    with connection.makefile("rb") as stream:
        message = stream.readline(MESSAGE_LIMIT + 1)
    if len(message) > MESSAGE_LIMIT or not message.endswith(b"\n"):
        raise ValueError("Invalid service control message")
    return message


def exchange(record: InstanceRecord, command: Literal["status", "stop"]) -> InstanceStatus:
    with socket.create_connection(
        ("127.0.0.1", record.port),
        CONTROL_TIMEOUT_SECONDS,
    ) as connection:
        connection.settimeout(CONTROL_TIMEOUT_SECONDS)
        request = (
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
        connection.sendall(request)
        status = InstanceStatus.model_validate_json(receive_message(connection))
    if status.pid != record.pid or status.fingerprint != record.fingerprint:
        raise ServiceError("Service instance identity does not match; no further action taken.")
    return status


class InstanceControl:
    def __init__(self, settings: Settings, config: Path, server: uvicorn.Server) -> None:
        self.settings = settings
        self.config = config
        self.server = server
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
            pid=os.getpid(),
            started_at=datetime.now(UTC),
            command=[sys.executable, *sys.orig_argv[1:]],
            port=self.listener.getsockname()[1],
            token=secrets.token_hex(32),
            project=str(PROJECT_ROOT),
            config=str(self.config),
            fingerprint=settings_fingerprint(self.settings),
        )
        path = runtime_path("instance.json")
        pending = runtime_path("instance.json.pending")
        # 独占实例锁期间替换遗留记录；凭据仅允许当前用户读取。
        pending.unlink(missing_ok=True)
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(self.record.model_dump_json())
        pending.replace(path)
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
                    # 未认证、超时或损坏的消息不影响服务，也不触发任何信号。
                    continue

    def _respond(self, connection: socket.socket) -> None:
        request = json.loads(receive_message(connection))
        record = self.record
        if record is None or not isinstance(request, dict):
            return
        token = request.get("token")
        if not isinstance(token, str) or not secrets.compare_digest(
            token.encode("utf-8"),
            record.token.encode("ascii"),
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
        response = InstanceStatus(pid=record.pid, fingerprint=record.fingerprint, phase=phase)
        try:
            connection.sendall(response.model_dump_json().encode() + b"\n")
        finally:
            if should_signal:
                os.kill(os.getpid(), signal.SIGINT)
