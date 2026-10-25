import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BACKEND_ROOT, PROJECT_ROOT, Settings
from app.database import (
    SessionDep,
    check_sqlite_version,
    create_database_engine,
    upgrade_database,
)
from app.main import create_app
from app.services.backup import backup_database
from tests.helpers import settings_for, write_config


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


def test_startup_does_not_create_database(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="Database missing"):
        with TestClient(create_app(settings), base_url="http://127.0.0.1"):
            pass
    assert not settings.data_dir.exists()


def test_unversioned_database_requires_explicit_migration(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path))
    settings.database_path.touch()
    with pytest.raises(RuntimeError, match="schema is not current"):
        with TestClient(create_app(settings), base_url="http://127.0.0.1"):
            pass
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_baseline_has_no_business_tables(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == [("alembic_version",)]


@pytest.mark.anyio
async def test_connection_settings_on_each_connection(settings: Settings) -> None:
    engine = create_database_engine(settings)
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
    engine = create_database_engine(settings)
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


def test_repeat_migration_preserves_records(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('keep me')")
    upgrade_database(settings)
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert connection.execute("SELECT value FROM probe").fetchone() == ("keep me",)


def test_paths_with_unicode_and_uri_characters(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "中文 # database"))
    upgrade_database(settings)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200


def test_busy_database_returns_retryable_error_without_partial_write(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.database_path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
    app = create_app(settings)

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
        first = await backup_database(settings)
        second = await backup_database(settings)
        assert first != second
        with closing(sqlite3.connect(first)) as snapshot:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert snapshot.execute("SELECT value FROM probe").fetchone() == ("snapshot data",)
        assert source.execute("SELECT value FROM probe").fetchone() == ("snapshot data",)


@pytest.mark.anyio
async def test_backup_missing_database_does_not_create_one(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, data_dir=str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="Database missing"):
        await backup_database(settings)
    assert not settings.data_dir.exists()


def test_openapi_export_needs_no_database_or_frontend(tmp_path: Path) -> None:
    data_dir = tmp_path / "no-database"
    frontend_dir = tmp_path / "no-frontend"
    config_file = write_config(
        tmp_path, data_dir=str(data_dir), frontend_dir=str(frontend_dir), serve_frontend=True
    )
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--config", str(config_file), "export-openapi"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(result.stdout)
    assert "/api/v1/hello" in schema["paths"]
    assert not data_dir.exists()
    assert not frontend_dir.exists()
