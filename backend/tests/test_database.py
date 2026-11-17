import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app import config as app_config
from app.application import create_app
from app.config import BACKEND_ROOT, PROJECT_ROOT, Settings
from app.infra import database as database_module
from app.infra.database import (
    SessionDep,
    check_sqlite_version,
    create_database_engine,
)
from app.maintenance.backup import DatabaseBackup
from app.utils.database_lock import ServiceError, operation_lock
from migrations.operations import migration_config, upgrade_database
from tests.helpers import read_config, save_config, settings_for, write_config


def test_paths_do_not_depend_on_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = settings_for(tmp_path, data_dir="relative-data")
    assert settings.data_dir == PROJECT_ROOT / "relative-data"


def test_runtime_rejects_old_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 50, 0))
    with pytest.raises(RuntimeError, match="SQLite 3.51.3"):
        check_sqlite_version()


@pytest.mark.anyio
async def test_database_path_override_preserves_process_settings_and_other_paths(
    tmp_path: Path,
) -> None:
    config_file = write_config(tmp_path / "configured")
    values = read_config(config_file)
    values["database"].update(journal_mode="DELETE", synchronous="EXTRA")
    save_config(config_file, values)
    configuration = app_config.load_settings(config_file)
    app_config.bind_settings(configuration)
    before = configuration.model_dump()
    target = tmp_path / "temporary" / "isolated.sqlite3"
    engine = create_database_engine(database_path=target, allow_create=True)
    try:
        async with engine.connect() as connection:
            databases = await connection.exec_driver_sql("PRAGMA database_list")
            main = next(row["file"] for row in databases.mappings() if row["name"] == "main")
            assert Path(main).resolve() == target.resolve()
            assert (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar() == "delete"
            assert (await connection.exec_driver_sql("PRAGMA synchronous")).scalar() == 3
            assert (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar() == 50
    finally:
        await engine.dispose()
    assert app_config.get_settings() is configuration
    assert configuration.model_dump() == before
    assert target.is_file()
    for directory in (
        configuration.data_dir,
        configuration.logging.directory,
        configuration.backup_directory,
        configuration.frontend_dir,
    ):
        assert not directory.exists()


@pytest.mark.parametrize("destination", ["relative", "source", "frontend", "log", "source-alias"])
def test_database_path_override_keeps_path_protection(
    settings: Settings, tmp_path: Path, destination: str
) -> None:
    if destination == "source-alias":
        alias = tmp_path / "source-alias"
        alias.symlink_to(PROJECT_ROOT / "backend", target_is_directory=True)
        target = alias / "probe.sqlite3"
    else:
        target = {
            "relative": Path("probe.sqlite3"),
            "source": PROJECT_ROOT / "backend/probe.sqlite3",
            "frontend": settings.frontend_dir / "probe.sqlite3",
            "log": settings.logging.directory / settings.logging.filename,
        }[destination]
    original = settings.database_path.read_bytes()
    with pytest.raises(ValueError):
        create_database_engine(database_path=target)
    assert settings.database_path.read_bytes() == original


def test_database_override_protects_module_project_root(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "isolated project"
    monkeypatch.setattr(database_module, "PROJECT_ROOT", project)
    target = project / "backend/protected.sqlite3"
    original = settings.database_path.read_bytes()
    with pytest.raises(ValueError, match="protected project source"):
        create_database_engine(database_path=target)
    assert not target.exists()
    assert settings.database_path.read_bytes() == original


def test_startup_does_not_create_database(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "absent"))
    app_config.bind_settings(settings)
    with pytest.raises(RuntimeError, match="Database missing"):
        with TestClient(create_app(), base_url="http://127.0.0.1"):
            pass
    assert not settings.data_dir.exists()


def test_unversioned_database_requires_explicit_migration(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "unversioned"))
    app_config.bind_settings(settings)
    settings.data_dir.mkdir()
    settings.database_path.touch()
    with pytest.raises(RuntimeError, match="schema is not current"):
        with TestClient(create_app(), base_url="http://127.0.0.1"):
            pass
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_baseline_has_no_business_tables(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app_config.bind_settings(settings)
    command.upgrade(migration_config(), "0001_baseline")
    with closing(sqlite3.connect(settings.database_path)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert tables == [("alembic_version",)]
    assert revision == ("0001_baseline",)


@pytest.mark.anyio
async def test_connection_settings_on_each_connection(settings: Settings) -> None:
    engine = create_database_engine()
    try:
        async with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar() == 1
                assert (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar() == "wal"
                assert (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar() == 50
                assert (await connection.exec_driver_sql("PRAGMA synchronous")).scalar() == 2
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_failed_transaction_rolls_back_all_writes(settings: Settings) -> None:
    engine = create_database_engine()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE probe (value TEXT NOT NULL)")
        async with AsyncSession(engine) as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await session.execute(text("INSERT INTO probe VALUES ('first')"))
                    await session.execute(text("INSERT INTO probe VALUES (NULL)"))
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("SELECT count(*) FROM probe")).scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_explicit_sqlite_transaction_rolls_back_ddl(settings: Settings) -> None:
    engine = create_database_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.exec_driver_sql("CREATE TABLE ddl_probe (value TEXT)")
            await transaction.rollback()
        async with engine.connect() as connection:
            table = await connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ddl_probe'"
            )
            assert table.scalar() is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_releasing_savepoint_does_not_commit_outer_transaction(settings: Settings) -> None:
    engine = create_database_engine()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE savepoint_probe (value TEXT)")
        async with engine.connect() as connection:
            transaction = await connection.begin()
            async with connection.begin_nested():
                await connection.exec_driver_sql("INSERT INTO savepoint_probe VALUES ('nested')")
            await transaction.rollback()
        async with engine.connect() as connection:
            count = await connection.exec_driver_sql("SELECT count(*) FROM savepoint_probe")
            assert count.scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_connection_never_recreates_database_removed_after_engine_creation(
    settings: Settings,
) -> None:
    engine = create_database_engine()
    settings.database_path.unlink()
    try:
        with pytest.raises(OperationalError, match="unable to open database file"):
            async with engine.connect():
                pytest.fail("Missing database was recreated")
        assert not settings.database_path.exists()
    finally:
        await engine.dispose()


def test_repeat_migration_preserves_records(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('keep me')")
    upgrade_database()
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert connection.execute("SELECT value FROM probe").fetchone() == ("keep me",)


def test_migration_refuses_running_application_without_touching_database(
    settings: Settings,
) -> None:
    with TestClient(create_app(), base_url="http://127.0.0.1"):
        original = settings.database_path.read_bytes()
        with pytest.raises(ServiceError, match="in progress"):
            upgrade_database()
        assert settings.database_path.read_bytes() == original
    upgrade_database()


def test_migration_cannot_race_service_operations(settings: Settings) -> None:
    with operation_lock(settings.database_path):
        with pytest.raises(ServiceError, match="in progress"):
            upgrade_database()


def test_paths_with_unicode_and_uri_characters(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "中文 # database"))
    app_config.bind_settings(settings)
    upgrade_database()
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200


def test_busy_database_returns_retryable_error_without_partial_write(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
    app = create_app()

    @app.post("/api/test-write")
    async def write(session: SessionDep) -> dict[str, bool]:
        async with session.begin():
            await session.execute(text("INSERT INTO probe VALUES ('once')"))
        return {"ok": True}

    with (
        TestClient(app, base_url="http://127.0.0.1") as client,
        closing(sqlite3.connect(settings.database_path, autocommit=True)) as writer,
    ):
        writer.execute("BEGIN IMMEDIATE")
        try:
            response = client.post("/api/test-write")
            assert response.status_code == 503
            assert response.json()["code"] == "DATABASE_BUSY"
        finally:
            writer.execute("ROLLBACK")
        assert client.post("/api/test-write").status_code == 200
        assert writer.execute("SELECT count(*) FROM probe").fetchone()[0] == 1


@pytest.mark.anyio
async def test_backup_includes_committed_wal_data_and_never_overwrites(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path, autocommit=True)) as source:
        source.execute("CREATE TABLE probe (value TEXT)")
        source.execute("INSERT INTO probe VALUES ('snapshot data')")
        backup = DatabaseBackup()
        first = await backup.create_snapshot()
        second = await backup.create_snapshot()
        assert first != second
        with closing(sqlite3.connect(first)) as snapshot:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert snapshot.execute("SELECT value FROM probe").fetchone() == ("snapshot data",)
        assert source.execute("SELECT value FROM probe").fetchone() == ("snapshot data",)


@pytest.mark.anyio
async def test_backup_names_stay_unique_when_timestamps_match(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 11, 6, tzinfo=UTC)
    monkeypatch.setattr("app.maintenance.backup.datetime", clock)

    backup = DatabaseBackup()
    first = await backup.create_snapshot()
    second = await backup.create_snapshot()
    assert first != second
    assert first.is_file() and second.is_file()
    for snapshot in (first, second):
        stamp, identifier = snapshot.stem.removeprefix("app-").split("-")
        assert stamp == "20261106T000000000000Z"
        assert len(identifier) == 32
        assert UUID(hex=identifier).version == 7


@pytest.mark.anyio
async def test_backup_missing_database_does_not_create_one(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "absent"))
    app_config.bind_settings(settings)
    with pytest.raises(RuntimeError, match="Database missing"):
        await DatabaseBackup().create_snapshot()
    assert not settings.data_dir.exists()


def test_openapi_export_needs_no_database_or_frontend(tmp_path: Path) -> None:
    data_dir = tmp_path / "no-database"
    frontend_dir = tmp_path / "no-frontend"
    config_file = write_config(
        tmp_path, data_dir=str(data_dir), frontend_dir=str(frontend_dir), serve_frontend=True
    )
    result = subprocess.run(
        [sys.executable, "-m", "entrypoints.cli", "--config", str(config_file), "export-openapi"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(result.stdout)
    assert "/api/v1/hello" in schema["paths"]
    assert not data_dir.exists()
    assert not frontend_dir.exists()
