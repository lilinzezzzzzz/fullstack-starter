import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.application as application_module
from app.application import create_app
from app.config import Settings
from app.infra.database import create_database_engine
from app.utils.database_lock import ServiceError, operation_lock
from migrations.operations import upgrade_database
from tests.helpers import settings_for


@pytest.mark.anyio
async def test_lifespans_use_each_applications_settings_and_provider(tmp_path: Path) -> None:
    configurations = [settings_for(tmp_path / name) for name in ("first", "second")]
    applications = [create_app(configuration) for configuration in configurations]
    shutdowns = []
    for application in applications:
        provider = application.state.tracer_provider
        shutdown = Mock(wraps=provider.shutdown)
        provider.shutdown = shutdown
        shutdowns.append(shutdown)

    try:
        for application, configuration, shutdown in zip(
            applications, configurations, shutdowns, strict=True
        ):
            await asyncio.to_thread(upgrade_database, configuration)
            async with application.router.lifespan_context(application):
                assert application.state.settings is configuration
                shutdown.assert_not_called()
                async with application.state.session_factory() as session:
                    databases = await session.execute(text("PRAGMA database_list"))
                    database_file = next(
                        row["file"] for row in databases.mappings() if row["name"] == "main"
                    )
                    assert Path(database_file).resolve() == configuration.database_path
            shutdown.assert_called_once_with()
            with operation_lock(configuration.database_path):
                pass
    finally:
        for shutdown in shutdowns:
            if not shutdown.called:
                shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_startup_failure_closes_resources_in_order(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    application = create_app(settings)
    engine = create_database_engine(settings)
    original_dispose = engine.dispose
    provider = application.state.tracer_provider
    original_shutdown = provider.shutdown
    original_complete = application_module.logger.complete
    closed = []

    async def dispose(actual_engine: AsyncEngine) -> None:
        assert actual_engine is engine
        with pytest.raises(ServiceError, match="in progress"):
            with operation_lock(settings.database_path):
                pytest.fail("Database lock released before engine disposal")
        await original_dispose()
        closed.append("engine")

    def shutdown() -> None:
        with operation_lock(settings.database_path):
            pass
        original_shutdown()
        closed.append("provider")

    async def complete_logging() -> None:
        await original_complete()
        closed.append("logs")

    async def fail_revision(actual_engine: AsyncEngine, actual_settings: Settings) -> None:
        assert actual_engine is engine
        assert actual_settings is settings
        raise failure("revision probe")

    shutdown_mock = Mock(side_effect=shutdown)
    complete_mock = AsyncMock(side_effect=complete_logging)
    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    monkeypatch.setattr(provider, "shutdown", shutdown_mock)
    monkeypatch.setattr(application_module, "logger", SimpleNamespace(complete=complete_mock))
    monkeypatch.setattr(application_module, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(application_module, "check_database_revision", fail_revision)

    with pytest.raises(failure, match="revision probe"):
        async with application.router.lifespan_context(application):
            pytest.fail("Application started after a failed revision check")

    shutdown_mock.assert_called_once_with()
    complete_mock.assert_awaited_once_with()
    assert closed == ["engine", "provider", "logs"]
    with operation_lock(settings.database_path):
        pass
