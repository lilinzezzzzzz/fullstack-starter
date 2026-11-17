"""在隔离环境中重放版本历史，并据此生成和检查迁移。"""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import MigrationScript
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from app.config import settings
from migrations.operations import migration_config


def discard_empty_revision(
    _context: MigrationContext,
    _revision: Sequence[str],
    directives: list[MigrationScript],
) -> None:
    if directives:
        operations = directives[0].upgrade_ops
        if operations is not None and operations.is_empty():
            directives.clear()


class DatabaseMigrations:
    """确保迁移开发独立于配置指定的应用数据库。"""

    def _temporary_directory(self) -> AbstractContextManager[str]:
        parent = settings.testing.temporary_directory
        parent.mkdir(parents=True, exist_ok=True)
        return TemporaryDirectory(prefix="migrations-", dir=parent)

    def _replay(self, directory: Path) -> Config:
        database_path = directory / "data" / settings.database_filename
        alembic_config = migration_config(database_path=database_path)
        heads = ScriptDirectory.from_config(alembic_config).get_heads()
        if len(heads) != 1:
            raise CommandError(
                f"Expected exactly one Alembic head; found {len(heads)}. "
                "Review the revision history before generating or checking migrations."
            )

        # 只切换本次迁移的数据库目标，进程配置和其他运行路径保持不变。
        command.upgrade(alembic_config, "head")
        return alembic_config

    def create_revision(self, message: str, *, empty: bool = False) -> Path | None:
        message = message.strip()
        if not message:
            raise ValueError("Migration message must not be blank.")
        with self._temporary_directory() as temporary:
            alembic_config = self._replay(Path(temporary))
            revision = command.revision(
                alembic_config,
                message=message,
                autogenerate=not empty,
                process_revision_directives=None if empty else discard_empty_revision,
            )
        if not revision:
            return None
        if isinstance(revision, list):
            raise RuntimeError("Expected a single generated migration.")
        return Path(revision.path)

    def check(self) -> None:
        with self._temporary_directory() as temporary:
            alembic_config = self._replay(Path(temporary))
            command.check(alembic_config)
