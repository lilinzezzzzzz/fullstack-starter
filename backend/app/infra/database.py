"""SQLite 引擎、连接策略与请求会话；运行资源由 lifespan 和调用方持有。"""

import sqlite3
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from alembic.migration import MigrationContext
from fastapi import Depends
from sqlalchemy import URL, Connection, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import PROJECT_ROOT, settings, validate_filename
from app.utils.path_safety import validate_runtime_paths
from migrations.operations import migration_heads

MIN_SQLITE_VERSION = (3, 51, 3)
_session_factory: async_sessionmaker[AsyncSession] | None = None


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            "SQLite 3.51.3+ is the scaffold's data-integrity baseline for the WAL-reset fix; "
            f"this Python uses {sqlite3.sqlite_version}. "
            "Use a Python build linked to a supported SQLite version; see README."
        )


def _resolve_database_path(database_path: Path | None) -> Path:
    """解析实际操作目标，临时路径与应用路径遵守同一安全边界。"""
    target = settings.database_path if database_path is None else database_path
    if not target.is_absolute():
        raise ValueError("Database target must be an absolute path")
    target = target.resolve()
    if database_path is not None:
        # 临时目标是操作参数，不是新的配置来源；保留原有路径保护。
        validate_filename(target.name)
        validate_runtime_paths(
            PROJECT_ROOT,
            frontend_dir=settings.frontend_dir,
            frontend_clean_output=settings.frontend_clean_output,
            data_dir=target.parent,
            backup_directory=settings.backup_directory,
            logging_directory=settings.logging.directory,
            temporary_directory=settings.testing.temporary_directory,
            database_filename=target.name,
            logging_filename=settings.logging.filename,
        )
    return target


def _configure_sqlite_connection(connection: Any, _record: object) -> None:
    # SQLAlchemy 传入 aiosqlite 的 DBAPI 适配器，游标通过 greenlet 桥接驱动 I/O。
    connection.isolation_level = None
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={int(settings.sqlite_timeout_seconds * 1000)}")
        cursor.execute(f"PRAGMA journal_mode={settings.database.journal_mode}")
        mode = cursor.fetchone()[0]
        if mode.upper() != settings.database.journal_mode:
            raise RuntimeError("Could not enable configured SQLite journal mode.")
        cursor.execute(f"PRAGMA synchronous={settings.database.synchronous}")
    finally:
        cursor.close()


def _begin_sqlite_transaction(connection: Connection) -> None:
    # 禁用驱动的 legacy BEGIN，由 SQLAlchemy 统一管理读、写和 DDL 事务。
    connection.exec_driver_sql("BEGIN")


def create_database_engine(
    *,
    database_path: Path | None = None,
    allow_create: bool = False,
) -> AsyncEngine:
    """创建 SQLite 引擎，默认禁止建库；调用方负责连接使用和引擎关闭。"""
    target = _resolve_database_path(database_path)
    check_sqlite_version()
    if allow_create:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.is_file():
        raise RuntimeError(
            "Database missing. Run entrypoints.cli db-upgrade with the same --config file."
        )

    # mode=rw 防止正常启动或重连时静默创建空数据库。
    url = URL.create(
        "sqlite+aiosqlite",
        database=f"file:{quote(str(target), safe='/')}",
        query={"uri": "true", "mode": "rwc" if allow_create else "rw"},
    )
    engine = create_async_engine(
        url=url,
        connect_args={
            "autocommit": sqlite3.LEGACY_TRANSACTION_CONTROL,
            "check_same_thread": False,
            "timeout": settings.sqlite_timeout_seconds,
        },
        hide_parameters=True,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout_seconds,
    )

    # 仅配置本次引擎，不在模块导入时注册全局监听器或打开连接。
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    event.listen(engine.sync_engine, "begin", _begin_sqlite_transaction)
    return engine


async def check_database_revision(engine: AsyncEngine) -> None:
    def current_heads(connection: Connection) -> set[str]:
        return set(MigrationContext.configure(connection).get_current_heads())

    async with engine.connect() as connection:
        current = await connection.run_sync(current_heads)
    if current != migration_heads():
        raise RuntimeError(
            "Database schema is not current. "
            "Run entrypoints.cli db-upgrade with the same --config file."
        )


@contextmanager
def session_factory_scope(engine: AsyncEngine) -> Generator[None]:
    """在 lifespan 中发布请求会话工厂，退出时清除，不负责关闭传入引擎。"""
    global _session_factory
    if _session_factory is not None:
        raise RuntimeError("Session factory is already initialized")
    try:
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
    finally:
        _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """每个请求独占 Session；事务由业务边界管理，此处不自动提交。"""
    session_factory = _session_factory
    if session_factory is None:
        raise RuntimeError("Session factory is not initialized; enter lifespan first")
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
