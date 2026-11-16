"""显式 TOML 驱动的单 worker 服务前台运行与后台启停入口。"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import uvicorn
from loguru import logger

from app.application import create_app
from app.config import BACKEND_ROOT, CONFIG_FILE, Settings, load_settings, resolve_project_path
from app.infra.logging import configure_logging
from app.utils.database_lock import ServiceError
from entrypoints.service_control import (
    POLL_INTERVAL_SECONDS,
    InstanceControl,
    exchange,
    instance_active,
    read_record,
    runtime_path,
    service_lock,
    settings_fingerprint,
)


def service_url(settings: Settings) -> str:
    host = settings.server.host
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{settings.server.port}"


def healthy(settings: Settings, timeout: float) -> bool:
    # 本地探测不经过继承的 HTTP_PROXY；Host 校验仍遵循应用配置。
    request = Request(service_url(settings) + "/api/health")
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            return response.status == 200 and json.load(response) == {
                "status": "ok",
                "database": "ok",
            }
    except OSError, ValueError:
        return False


def run_service(settings: Settings, config: Path) -> None:
    with service_lock(runtime_path("run.lock")):
        control: InstanceControl | None = None
        try:
            configure_logging(settings.logging)
            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(settings),
                    host=settings.server.host,
                    port=settings.server.port,
                    workers=settings.server.workers,
                    timeout_graceful_shutdown=settings.server.graceful_shutdown_seconds,
                    timeout_keep_alive=settings.server.keep_alive_seconds,
                    backlog=settings.server.backlog,
                    limit_concurrency=(
                        None
                        if settings.server.concurrency_limit == 0
                        else settings.server.concurrency_limit
                    ),
                    log_config=None,
                    access_log=False,
                    proxy_headers=False,
                    forwarded_allow_ips=[],
                )
            )
            control = InstanceControl(settings, config, server)
            control.start()
            try:
                server.run()
            except KeyboardInterrupt:
                return
            if not server.started:
                raise ServiceError("Application startup failed; inspect the application log.")
        finally:
            # 实例锁覆盖末尾日志排空，stop 返回后可以安全执行离线维护。
            # Uvicorn 已结束信号处理；重复 SIGINT 不应再打断末尾资源清理。
            previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                if control is not None:
                    control.stopping.set()
                logger.complete()
            finally:
                try:
                    if control is not None:
                        control.close()
                finally:
                    signal.signal(signal.SIGINT, previous_sigint)


def report_status(settings: Settings, config: Path) -> int:
    record = read_record(config)
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
    if record.fingerprint != settings_fingerprint(settings):
        print(f"config-changed: PID {record.pid}; use restart to apply changes")
        return 1
    if state.phase == "running":
        phase = "healthy" if healthy(settings, 1.0) else "unhealthy"
    else:
        phase = state.phase
    print(f"{phase}: PID {record.pid}; {service_url(settings)}")
    return 0 if phase == "healthy" else 1


def stop_service(settings: Settings, config: Path) -> None:
    deadline = time.monotonic() + settings.service.stop_timeout_seconds
    requested = False
    while instance_active():
        record = read_record(config)
        if record is not None and not requested:
            # 配置内容更新后，仍可通过同一配置路径安全停止旧实例。
            try:
                exchange(record, "stop")
                requested = True
            except (OSError, ValueError) as exc:
                if instance_active():
                    raise ServiceError(
                        "Control channel unavailable; instance retained, no signal sent."
                    ) from exc
        if time.monotonic() >= deadline:
            raise ServiceError(
                "Stop timed out; instance retained, no force kill or restart performed."
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    print("stopped" if requested else "already stopped")


def start_service(settings: Settings, config: Path) -> None:
    fingerprint = settings_fingerprint(settings)
    record = read_record(config)
    if record is not None:
        if record.fingerprint != fingerprint:
            raise ServiceError("Configuration changed; use restart to apply it.")
        state = exchange(record, "status")
        if state.phase == "running" and healthy(settings, 1.0):
            print(f"already running: PID {record.pid}; {service_url(settings)}")
            return
        raise ServiceError("Existing instance is not healthy; inspect status/logs or use restart.")
    if instance_active():
        raise ServiceError("Instance registration is in progress; retry status shortly.")

    # 仅在运行锁空闲时移除遗留记录，避免子进程拿锁后、登记前误读旧身份。
    with service_lock(runtime_path("run.lock")):
        runtime_path("instance.json").unlink(missing_ok=True)

    output_path = runtime_path("console.log")
    log_path = settings.logging.directory / settings.logging.filename
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "ab") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "entrypoints.service", "run", "--config", str(config)],
            cwd=BACKEND_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + settings.service.startup_timeout_seconds
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ServiceError(
                    f"Service exited during startup; inspect {output_path} and {log_path}."
                )
            record = read_record(config)
            if record is not None and record.pid == process.pid:
                if record.fingerprint != fingerprint:
                    raise ServiceError(
                        "Configuration changed during startup; retry with stable TOML."
                    )
                state = exchange(record, "status")
                remaining = max(0.01, deadline - time.monotonic())
                if state.phase == "running" and healthy(settings, min(1.0, remaining)):
                    print(f"started: PID {record.pid}; {service_url(settings)}")
                    print(f"log: {log_path}")
                    print(f"startup output: {output_path}")
                    return
            time.sleep(POLL_INTERVAL_SECONDS)
        raise ServiceError(f"Startup timed out; inspect {output_path} and {log_path}.")
    except BaseException:
        # 仅回收本次创建且尚未被 wait 回收的子进程；不按文件 PID 或端口发信号。
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=settings.service.stop_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise ServiceError(
                    "Startup cleanup timed out; instance retained, no force kill performed."
                ) from exc
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the local single-worker service")
    parser.add_argument("command", choices=("run", "start", "status", "stop", "restart"))
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()
    try:
        config = resolve_project_path(args.config)
        settings = load_settings(config)
        if args.command == "run":
            run_service(settings, config)
        elif args.command == "status":
            raise SystemExit(report_status(settings, config))
        else:
            with service_lock(runtime_path("control.lock")):
                if args.command in ("stop", "restart"):
                    stop_service(settings, config)
                if args.command in ("start", "restart"):
                    start_service(settings, config)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
