"""Configure Alembic and explicitly upgrade the selected application database."""

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import BACKEND_ROOT, Settings
from app.service_state import ServiceError, operation_lock


def migration_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.attributes["settings"] = settings
    return config


def migration_heads(settings: Settings) -> set[str]:
    return set(ScriptDirectory.from_config(migration_config(settings)).get_heads())


def upgrade_database(settings: Settings) -> None:
    """Own the offline maintenance lock; env.py owns and disposes its async engine."""
    with operation_lock(settings.service.pid_file):
        if settings.service.pid_file.exists():
            raise ServiceError(
                "Stop the service with sh scripts/service.sh stop using the same --config "
                "before db-upgrade. An existing PID file is left untouched."
            )
        command.upgrade(migration_config(settings), "head")
