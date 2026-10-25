"""Coordinate service controllers and offline database maintenance."""

import fcntl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


class ServiceError(RuntimeError):
    pass


@contextmanager
def operation_lock(pid_file: Path) -> Generator[None]:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with pid_file.with_suffix(pid_file.suffix + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ServiceError("Another service or maintenance operation is in progress.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
