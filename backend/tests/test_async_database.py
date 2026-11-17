import asyncio
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager, closing
from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text

from app.config import BACKEND_ROOT, Settings
from app.infra.database import create_database_engine, get_session, session_factory_scope
from app.maintenance.backup import DatabaseBackup
from migrations.operations import migration_heads


@pytest.mark.anyio
async def test_cancelled_request_rolls_back_and_returns_connection(settings: Settings) -> None:
    engine = create_database_engine()
    entered = asyncio.Event()
    waiting = asyncio.Event()
    session_context = asynccontextmanager(get_session)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE probe (value TEXT)")

        async def write_then_wait() -> None:
            async with session_context() as session:
                async with session.begin():
                    await session.execute(text("INSERT INTO probe VALUES ('not committed')"))
                    entered.set()
                    await waiting.wait()

        with session_factory_scope(engine):
            task = asyncio.create_task(write_then_wait())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert engine.pool.checkedout() == 0
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("SELECT count(*) FROM probe")).scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_session_dependency_closes_without_implicitly_committing(settings: Settings) -> None:
    engine = create_database_engine()
    session_context = asynccontextmanager(get_session)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE session_probe (value TEXT)")
        with session_factory_scope(engine):
            async with session_context() as session:
                await session.execute(text("INSERT INTO session_probe VALUES ('not committed')"))
        assert engine.pool.checkedout() == 0
        async with engine.connect() as connection:
            count = await connection.exec_driver_sql("SELECT count(*) FROM session_probe")
            assert count.scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_requests_receive_independent_sessions(settings: Settings) -> None:
    engine = create_database_engine()
    session_context = asynccontextmanager(get_session)
    both_entered = asyncio.Event()
    entered = []

    async def use_session():
        async with session_context() as session:
            await session.execute(text("SELECT 1"))
            entered.append(session)
            if len(entered) == 2:
                both_entered.set()
            await both_entered.wait()
            return session

    try:
        with session_factory_scope(engine):
            first, second = await asyncio.gather(use_session(), use_session())
        assert first is not second
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_session_factory_scope_rejects_missing_and_duplicate_initialization(
    settings: Settings,
) -> None:
    session_context = asynccontextmanager(get_session)
    with pytest.raises(RuntimeError, match="not initialized"):
        async with session_context():
            pytest.fail("Session available before initialization")
    engine = create_database_engine()
    try:
        with session_factory_scope(engine):
            with pytest.raises(RuntimeError, match="already initialized"):
                with session_factory_scope(engine):
                    pytest.fail("Duplicate initialization succeeded")
            # 失败的重复初始化不能清除原作用域持有的工厂。
            async with session_context() as session:
                assert session.bind is engine
                assert (await session.execute(text("SELECT 1"))).scalar() == 1
        with pytest.raises(RuntimeError, match="not initialized"):
            async with session_context():
                pytest.fail("Session available after shutdown")
        # 清除后可以由下一次独立生命周期重新初始化。
        with session_factory_scope(engine):
            async with session_context() as session:
                assert session.bind is engine
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_session_factory_scope_clears_after_exception_or_cancellation(
    settings: Settings, failure: type[BaseException]
) -> None:
    engine = create_database_engine()
    session_context = asynccontextmanager(get_session)
    try:
        with pytest.raises(failure, match="scope probe"):
            with session_factory_scope(engine):
                async with session_context() as session:
                    assert session.bind is engine
                raise failure("scope probe")
        with pytest.raises(RuntimeError, match="not initialized"):
            async with session_context():
                pytest.fail("Factory retained after failed scope")
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_cancelled_backup_propagates_and_removes_partial_file(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def cancelled_copy(_source, _target) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(aiosqlite.Connection, "backup", cancelled_copy)
    with pytest.raises(asyncio.CancelledError):
        await DatabaseBackup().create_snapshot()
    assert list(settings.backup_directory.iterdir()) == []
    assert settings.database_path.is_file()


def test_backup_cli_runs_and_closes_its_async_connections(
    settings: Settings, tmp_path: Path
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "entrypoints.cli",
            "--config",
            str(tmp_path / "settings.toml"),
            "db-backup",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    snapshot = Path(result.stdout.strip())
    assert snapshot.parent == settings.backup_directory
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        assert {row[0] for row in rows} == migration_heads()


@pytest.mark.anyio
async def test_backup_cancellation_waits_for_copy_before_closing_target(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    completed = asyncio.Event()
    calls = []

    async def delayed_copy(_source, target) -> None:
        calls.append("copy")
        started.set()
        await finish.wait()
        async with target.execute("CREATE TABLE copied_data (value TEXT)"):
            pass
        completed.set()

    monkeypatch.setattr(aiosqlite.Connection, "backup", delayed_copy)
    backup = DatabaseBackup()
    task = asyncio.create_task(backup.create_snapshot())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["copy"]
    assert completed.is_set()
    assert list(settings.backup_directory.iterdir()) == []
