"""Single-worker service lifecycle behind scripts/service.sh (macOS/Linux)."""

import argparse
import asyncio
import fcntl
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from loguru import logger

from app.config import BACKEND_ROOT, CONFIG_FILE, Settings, load_settings, resolve_project_path
from app.logging_setup import configure_logging

SERVICE_MODULE = "tools.service_control"


class ServiceError(RuntimeError):
    pass


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content.isdecimal() or len(content) > 10 or int(content) <= 1:
        raise ServiceError(f"Invalid PID file; left untouched: {path}")
    return int(content)


def process_info(pid: int, inspection_timeout: float) -> tuple[str, str] | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        raise ServiceError(f"Cannot inspect PID {pid}; no signal was sent.") from exc

    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "stat=", "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=inspection_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"Inspection of PID {pid} timed out; no signal was sent.") from exc
    if result.returncode:
        if result.returncode == 1 and not result.stderr.strip():
            return None
        raise ServiceError(f"Cannot verify PID {pid}; no signal was sent.")
    state, _, command = result.stdout.strip().partition(" ")
    if state.startswith("Z"):
        return None
    return state, command


def is_owned_process(pid: int, config_file: Path, inspection_timeout: float) -> bool:
    info = process_info(pid, inspection_timeout)
    if info is None:
        return False
    _state, command = info
    if f" -m {SERVICE_MODULE} run " not in command or not command.endswith(
        f"--config {config_file}",
    ):
        raise ServiceError(f"PID {pid} is not this service; PID file and process left untouched.")
    return True


@contextmanager
def operation_lock(pid_file: Path):
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with pid_file.with_suffix(pid_file.suffix + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ServiceError("Another service operation is in progress.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def remove_pid(path: Path, expected: int) -> None:
    if read_pid(path) != expected:
        raise ServiceError("PID file changed during the operation; left untouched.")
    path.unlink()


def start_service(settings: Settings, config_file: Path) -> None:
    pid_file = settings.service.pid_file
    existing = read_pid(pid_file)
    if existing is not None:
        if is_owned_process(existing, config_file, settings.service.inspection_timeout_seconds):
            print(f"Already running: PID {existing}")
            return
        remove_pid(pid_file, existing)

    settings.logging.directory.mkdir(parents=True, exist_ok=True)
    bootstrap_log = settings.logging.directory / settings.logging.bootstrap_filename
    read_fd, write_fd = os.pipe()
    try:
        with bootstrap_log.open("ab") as output:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    SERVICE_MODULE,
                    "run",
                    "--ready-fd",
                    str(write_fd),
                    "--config",
                    str(config_file),
                ],
                cwd=BACKEND_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(write_fd,),
            )
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        raise
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], settings.service.startup_timeout_seconds)
        if not ready or os.read(read_fd, 1) != b"1" or child.poll() is not None:
            raise ServiceError(
                f"Startup failed. Check {bootstrap_log} and {settings.logging.filename}"
            )
        with pid_file.open("x") as handle:
            handle.write(f"{child.pid}\n")
        print(f"Started: PID {child.pid}, http://{settings.server.host}:{settings.server.port}/")
        print(f"PID file: {pid_file}")
    except BaseException:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=settings.service.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                if not pid_file.exists():
                    pid_file.write_text(f"{child.pid}\n")
                raise ServiceError(
                    f"Startup did not finish; live PID {child.pid} retained."
                ) from exc
        if pid_file.exists() and read_pid(pid_file) == child.pid:
            remove_pid(pid_file, child.pid)
        raise
    finally:
        os.close(read_fd)


def stop_service(settings: Settings, config_file: Path) -> None:
    pid_file = settings.service.pid_file
    pid = read_pid(pid_file)
    if pid is None:
        print("Already stopped.")
        return
    if not is_owned_process(pid, config_file, settings.service.inspection_timeout_seconds):
        remove_pid(pid_file, pid)
        print("Stopped; stale PID file removed.")
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + settings.service.shutdown_timeout_seconds
    while time.monotonic() < deadline:
        # During normal exit macOS may replace argv before reaping the PID.
        # Ownership was checked before SIGTERM; polling must not send more signals.
        if process_info(pid, settings.service.inspection_timeout_seconds) is None:
            remove_pid(pid_file, pid)
            print(f"Stopped: PID {pid}")
            return
        time.sleep(settings.service.shutdown_poll_seconds)
    raise ServiceError(f"PID {pid} has not exited; PID file retained. No SIGKILL was sent.")


def service_status(settings: Settings, config_file: Path) -> int:
    pid = read_pid(settings.service.pid_file)
    if pid is not None and is_owned_process(
        pid, config_file, settings.service.inspection_timeout_seconds
    ):
        print(f"Running: PID {pid}, port {settings.server.port}")
        return 0
    print("Stopped." if pid is None else "Stopped; stale PID file exists.")
    return 3


async def serve(settings: Settings, ready_fd: int | None) -> None:
    from app.main import create_app

    server = uvicorn.Server(
        config=uvicorn.Config(
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
    task = asyncio.create_task(server.serve())
    try:
        while not server.started and not task.done():
            await asyncio.sleep(settings.service.readiness_poll_seconds)
        if ready_fd is not None and server.started:
            os.write(ready_fd, b"1")
        if ready_fd is not None:
            os.close(ready_fd)
            ready_fd = None
        await task
    finally:
        if ready_fd is not None:
            os.close(ready_fd)
        if not task.done():
            server.should_exit = True
            await task


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the local single-worker service")
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "run"))
    # The entry file is a bootstrap convention, never a source of fallback values.
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    parser.add_argument("--ready-fd", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action != "run":

        def interrupt(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupt)
    try:
        config_file = resolve_project_path(args.config)
        settings = load_settings(config_file)
        if args.action == "run":
            configure_logging(settings.logging)
            try:
                asyncio.run(serve(settings, args.ready_fd))
            except Exception:
                logger.exception("Service startup failed")
                raise
        elif args.action == "status":
            raise SystemExit(service_status(settings, config_file))
        else:
            with operation_lock(settings.service.pid_file):
                if args.action in ("stop", "restart"):
                    stop_service(settings, config_file)
                if args.action in ("start", "restart"):
                    start_service(settings, config_file)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Service operation interrupted.\n")


if __name__ == "__main__":
    main()
