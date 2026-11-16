"""项目服务入口：延迟配置加载、认证单实例管理与明确的退出码。"""

import argparse
import hashlib
import signal
from contextlib import ExitStack
from pathlib import Path
from types import FrameType

import uvicorn
from loguru import logger

from app.application import create_app
from app.config import CONFIG_FILE
from app.infra.logging import configure_logging
from entrypoints.service_control import (
    COMMAND_LOCK_TIMEOUT_SECONDS,
    InstanceControl,
    ServiceController,
    runtime_path,
    service_lock,
)


def run_service(controller: ServiceController, *, background_child: bool = False) -> None:
    with ExitStack() as lifetime:
        with ExitStack() as registration:
            if not background_child:
                registration.enter_context(
                    service_lock(runtime_path("control.lock"), COMMAND_LOCK_TIMEOUT_SECONDS)
                )
                if controller.report_existing():
                    return
            lifetime.enter_context(service_lock(runtime_path("run.lock")))
            previous_term = signal.signal(signal.SIGTERM, exit_from_sigterm)
            lifetime.callback(signal.signal, signal.SIGTERM, previous_term)
            control: InstanceControl | None = None
            try:
                settings = controller.startup_settings()
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
                        limit_concurrency=settings.server.concurrency_limit or None,
                        log_config=None,
                        access_log=False,
                        proxy_headers=False,
                        forwarded_allow_ips=[],
                    )
                )
                control = InstanceControl(
                    settings, server, hashlib.sha256(controller.startup_snapshot()).hexdigest()
                )
                control.start()
            except BaseException:
                finish_instance(control)
                raise
            lifetime.callback(finish_instance, control)
        try:
            server.run()
        except SystemExit as exc:
            # 新版 Uvicorn 以 3 报启动失败；本入口只把 3 用于 status 的已停止状态。
            if exc.code == 3:
                raise RuntimeError(
                    "Application startup failed; inspect the application log"
                ) from exc
            raise
        if not server.started:
            raise RuntimeError("Application startup failed; inspect the application log")


def exit_from_sigterm(signum: int, frame: FrameType | None) -> None:
    # Uvicorn 优雅关闭后重发原信号；用可展开 Python 栈的退出保留末尾清理。
    raise SystemExit(128 + signum)


def finish_instance(control: InstanceControl | None) -> None:
    # Uvicorn 已恢复原信号处理器，重复退出信号不得打断日志和状态清理。
    previous = {
        signum: signal.signal(signum, signal.SIG_IGN) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if control is not None:
            control.stopping.set()
        try:
            logger.complete()
        finally:
            if control is not None:
                control.close()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local single-instance service")
    parser.add_argument("command", choices=("run", "start", "status", "stop", "restart"))
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_FILE,
        help="Configuration for a new instance (default: configs/app.toml); "
        "ignored by status/stop and start/run when already running",
    )
    parser.add_argument("--settings-fd", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.settings_fd is not None and (args.command != "run" or args.settings_fd < 3):
        parser.error("Startup snapshot descriptors are only valid for background run")
    previous_term = signal.signal(signal.SIGTERM, exit_from_sigterm)
    try:
        controller = ServiceController(config_file=args.config)
        if args.command == "run":
            if args.settings_fd is not None:
                controller.restore_snapshot(args.settings_fd)
            run_service(controller, background_child=args.settings_fd is not None)
            return 0
        return controller.execute(args.command)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
