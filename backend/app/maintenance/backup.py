"""为本地维护 CLI 提供经过校验的 SQLite 快照。"""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import aiosqlite

from app.config import Settings
from app.infra.database import check_sqlite_version
from migrations.operations import migration_heads


class DatabaseBackup:
    """以独占方式创建并校验快照，不负责管理服务状态。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create_snapshot(self) -> Path:
        settings = self._settings
        check_sqlite_version()
        if not settings.database_path.is_file():
            raise RuntimeError(
                "Database missing. Run db-upgrade with the same --config file first."
            )

        backup_dir = settings.backup_directory
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        # UUIDv7 前部是时间戳，保留完整值以避免截断后丢失唯一性信息。
        target = backup_dir / f"app-{stamp}-{uuid7().hex}.sqlite3"
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            source_uri = f"{settings.database_path.as_uri()}?mode=ro"
            async with (
                aiosqlite.connect(source_uri, uri=True, autocommit=True) as source,
                aiosqlite.connect(target, autocommit=True) as destination,
            ):
                # 任务取消后，SQLite 原生备份仍会在驱动的工作线程中继续执行。
                # 关闭目标连接或删除未完成的快照之前，须等待本次复制结束。
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
                    raise RuntimeError(
                        "Backup schema is not current; review migrations before use."
                    )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


def new_database_backup(settings: Settings) -> DatabaseBackup:
    """为维护 CLI 组装依赖并创建实例。"""
    return DatabaseBackup(settings)
