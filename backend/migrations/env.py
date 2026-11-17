import asyncio
from pathlib import Path

from alembic import context
from sqlalchemy import Connection

from app.infra.database import create_database_engine
from app.models import Base

alembic_config = context.config


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
    database_path = alembic_config.attributes.get("database_path")
    if not isinstance(database_path, Path) or not database_path.is_absolute():
        raise ValueError("An explicit absolute database_path is required for migrations")
    engine = create_database_engine(database_path=database_path, allow_create=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
