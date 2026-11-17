"""配置 Alembic，并显式升级选定的应用数据库。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import BACKEND_ROOT, settings
from app.utils.database_lock import operation_lock


def migration_config(*, database_path: Path | None = None) -> Config:
    target = settings.database_path if database_path is None else database_path
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    alembic_config.attributes["database_path"] = target
    return alembic_config


def migration_heads() -> set[str]:
    """读取源码中的迁移版本，不依赖应用配置或数据库。"""
    return set(ScriptDirectory(str(BACKEND_ROOT / "migrations")).get_heads())


def upgrade_database() -> None:
    """管理离线维护锁；异步引擎由 env.py 管理并释放。"""
    with operation_lock(settings.database_path):
        command.upgrade(migration_config(), "head")
