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

from app.config import Settings
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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _temporary_directory(self) -> AbstractContextManager[str]:
        parent = self._settings.testing.temporary_directory
        parent.mkdir(parents=True, exist_ok=True)
        return TemporaryDirectory(prefix="migrations-", dir=parent)

    def _replay(self, directory: Path) -> Config:
        config = migration_config(self._settings)
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise CommandError(
                f"Expected exactly one Alembic head; found {len(heads)}. "
                "Review the revision history before generating or checking migrations."
            )

        # 完整的 TOML 配置已通过校验；这些资源路径用于强制隔离，
        # 不作为缺失配置字段的回退值。
        values = self._settings.model_dump()
        values.update(
            data_dir=directory / "data",
            backup_directory=directory / "backups",
            frontend_dir=directory / "dist",
            serve_frontend=False,
            frontend_clean_output=False,
        )
        values["logging"]["directory"] = directory / "logs"
        config.attributes["settings"] = Settings.model_validate(values)
        command.upgrade(config, "head")
        return config

    def create_revision(self, message: str, *, empty: bool = False) -> Path | None:
        message = message.strip()
        if not message:
            raise ValueError("Migration message must not be blank.")
        with self._temporary_directory() as temporary:
            config = self._replay(Path(temporary))
            revision = command.revision(
                config,
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
            config = self._replay(Path(temporary))
            command.check(config)


def new_database_migrations(settings: Settings) -> DatabaseMigrations:
    """为维护 CLI 组装依赖并创建实例。"""
    return DatabaseMigrations(settings)
