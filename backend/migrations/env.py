import asyncio

from alembic import context
from sqlalchemy import Connection

from app.config import CONFIG_FILE, load_settings
from app.database import create_database_engine
from app.models import Base

config = context.config


def run_migrations_offline() -> None:
    context.configure(
        url="sqlite://",
        target_metadata=Base.metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = config.attributes.get("settings")
    if settings is None:
        settings = load_settings(CONFIG_FILE)
    engine = create_database_engine(settings, allow_create=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
