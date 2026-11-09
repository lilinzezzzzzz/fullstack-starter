"""通过数据库旁的文件锁协调运行服务与离线迁移。"""

import fcntl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


class ServiceError(RuntimeError):
    pass


@contextmanager
def operation_lock(database_path: Path) -> Generator[None]:
    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with database_path.with_suffix(database_path.suffix + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ServiceError("Another service or maintenance operation is in progress.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
