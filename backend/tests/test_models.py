import pytest
from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, Index, MetaData, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.config import Settings
from app.database import create_database_engine
from app.models import Base


@pytest.mark.anyio
async def test_representative_model_builds_and_autogenerates_distinct_indexes(
    settings: Settings,
) -> None:
    class Example(Base):
        __tablename__ = "model_probe"
        metadata = MetaData(naming_convention=Base.metadata.naming_convention)

        id: Mapped[int] = mapped_column(primary_key=True)
        a: Mapped[int]
        b: Mapped[int]
        c: Mapped[int]

        __table_args__ = (
            Index(None, "a", "b"),
            Index(None, "a", "c"),
            UniqueConstraint("a", "b"),
            UniqueConstraint("a", "c"),
            CheckConstraint("a > 0"),
            CheckConstraint("b > 0", name="ck_model_probe_positive_b"),
        )

    def verify(connection: Connection) -> None:
        context = MigrationContext.configure(connection)
        migration = produce_migrations(context, Example.metadata)
        source = render_python_code(migration.upgrade_ops)
        for name in (
            "ix_model_probe_a_b",
            "ix_model_probe_a_c",
            "uq_model_probe_a_b",
            "uq_model_probe_a_c",
        ):
            assert name in source
        Example.metadata.create_all(connection)
        assert produce_migrations(context, Example.metadata).upgrade_ops.is_empty()

    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(verify)
    finally:
        await engine.dispose()
