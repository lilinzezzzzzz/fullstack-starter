"""Verified SQLite snapshots for the local maintenance CLI."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite

from app.config import Settings
from app.database import check_sqlite_version, migration_heads


async def backup_database(settings: Settings) -> Path:
    check_sqlite_version()
    if not settings.database_path.is_file():
        raise RuntimeError("Database missing. Run db-upgrade with the same --config file first.")
    backup_dir = settings.backup_directory
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"app-{stamp}-{uuid4().hex[:8]}.sqlite3"
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        source_uri = f"{settings.database_path.as_uri()}?mode=ro"
        async with (
            aiosqlite.connect(source_uri, uri=True, autocommit=True) as source,
            aiosqlite.connect(target, autocommit=True) as destination,
        ):
            # SQLite's native backup continues on the driver's worker after task cancellation.
            # Drain that one copy before closing its target or removing the partial snapshot.
            copy = asyncio.create_task(source.backup(destination))
            try:
                await asyncio.shield(copy)
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.gather(copy, return_exceptions=True))
                raise
            async with destination.execute("PRAGMA integrity_check") as cursor:
                integrity = await cursor.fetchone()
            if integrity != ("ok",):
                raise RuntimeError("Backup integrity check failed.")
            async with destination.execute("SELECT version_num FROM alembic_version") as cursor:
                current = {row[0] for row in await cursor.fetchall()}
            if current != migration_heads(settings):
                raise RuntimeError("Backup schema is not current; review migrations before use.")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
