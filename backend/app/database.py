import sqlite3
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, Request
from sqlalchemy import URL, Connection, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import BACKEND_ROOT, Settings
from app.service_state import ServiceError, operation_lock

MIN_SQLITE_VERSION = (3, 51, 3)


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            "SQLite 3.51.3+ is the scaffold's data-integrity baseline for the WAL-reset fix; "
            f"this Python uses {sqlite3.sqlite_version}. "
            "Use a Python build linked to a supported SQLite version; see README."
        )


def migration_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.attributes["settings"] = settings
    return config


def migration_heads(settings: Settings) -> set[str]:
    return set(ScriptDirectory.from_config(migration_config(settings)).get_heads())


def create_database_engine(settings: Settings, *, allow_create: bool = False) -> AsyncEngine:
    check_sqlite_version()
    if allow_create:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    elif not settings.database_path.is_file():
        raise RuntimeError("Database missing. Run app.cli db-upgrade with the same --config file.")

    # mode=rw prevents normal startup or reconnects from silently creating an empty database.
    url = URL.create(
        "sqlite+aiosqlite",
        database=f"file:{quote(str(settings.database_path), safe='/')}",
        query={"uri": "true", "mode": "rwc" if allow_create else "rw"},
    )
    engine = create_async_engine(
        url,
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

    @event.listens_for(engine.sync_engine, "connect")
    def configure_connection(connection, _record: object) -> None:
        # aiosqlite's event adapter awaits driver I/O through SQLAlchemy's greenlet bridge.
        # Disable driver BEGIN; the SQLAlchemy begin event below owns transaction control.
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

    @event.listens_for(engine.sync_engine, "begin")
    def begin_transaction(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


async def check_database_revision(engine: AsyncEngine, settings: Settings) -> None:
    def current_heads(connection: Connection) -> set[str]:
        return set(MigrationContext.configure(connection).get_current_heads())

    async with engine.connect() as connection:
        current = await connection.run_sync(current_heads)
    if current != migration_heads(settings):
        raise RuntimeError(
            "Database schema is not current. Run app.cli db-upgrade with the same --config file."
        )


def upgrade_database(settings: Settings) -> None:
    """Synchronous CLI/setup boundary; env.py runs and disposes its own async engine."""
    with operation_lock(settings.service.pid_file):
        if settings.service.pid_file.exists():
            raise ServiceError(
                "Stop the service with sh scripts/service.sh stop using the same --config "
                "before db-upgrade. An existing PID file is left untouched."
            )
        command.upgrade(migration_config(settings), "head")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
