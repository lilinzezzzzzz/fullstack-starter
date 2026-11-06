"""配置 Alembic，并显式升级选定的应用数据库。"""

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import BACKEND_ROOT, Settings
from app.service_state import operation_lock


def migration_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.attributes["settings"] = settings
    return config


def migration_heads(settings: Settings) -> set[str]:
    return set(ScriptDirectory.from_config(migration_config(settings)).get_heads())


def upgrade_database(settings: Settings) -> None:
    """管理离线维护锁；异步引擎由 env.py 管理并释放。"""
    with operation_lock(settings.database_path):
        command.upgrade(migration_config(settings), "head")
