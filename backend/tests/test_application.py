import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.application as application_module
from app import config
from app.application import create_app
from app.config import Settings
from app.infra.database import create_database_engine, get_session
from app.telemetry import get_tracer_provider
from app.telemetry import provider as telemetry_provider
from app.utils.database_lock import ServiceError, operation_lock
from migrations.operations import upgrade_database
from tests.helpers import settings_for, write_config


@pytest.mark.parametrize(
    "module",
    [
        "app.application",
        "entrypoints.cli",
        "app.infra.middleware",
        "app.infra.logging",
        "app.infra.database",
        "app.infra.frontend",
        "app.telemetry.environment",
        "app.telemetry.provider",
        "app.telemetry.adapter",
        "migrations.operations",
        "migrations.development",
        "app.maintenance.backup",
    ],
)
def test_plain_import_does_not_load_settings_or_create_runtime_resources(
    service_project: Path, tmp_path: Path, module: str
) -> None:
    (service_project / "configs/app.toml").unlink()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import importlib
                import sys
                from app import config
                assert repr(config.settings) == "<_LazyProxy>"
                def unexpected_configuration_read(path):
                    raise AssertionError("Plain import read TOML")
                config.load_settings = unexpected_configuration_read
                importlib.import_module(sys.argv[1])
            """),
            module,
        ],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(tmp_path / "missing.toml")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (service_project / ".run").exists()
    assert not (service_project / "logs").exists()
    assert not (service_project / ".data").exists()


def test_asgi_entry_assembles_shared_settings_without_runtime_side_effects(
    service_project: Path, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "runtime config", serve_frontend=True)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import asyncio
                import sys
                from contextlib import asynccontextmanager
                from app.infra.database import get_session
                from app.telemetry import get_tracer_provider
                from app.telemetry import provider as telemetry_provider

                def unexpected_provider_creation():
                    raise AssertionError("SDK provider created while importing ASGI app")

                telemetry_provider._create_tracer_provider = unexpected_provider_creation
                from entrypoints.api import app
                from app.config import settings

                async def check_uninitialized_factory():
                    try:
                        async with asynccontextmanager(get_session)():
                            raise AssertionError("Session available without lifespan")
                    except RuntimeError as exc:
                        assert "not initialized" in str(exc)

                assert not hasattr(app.state, "settings")
                assert not hasattr(app.state, "session_factory")
                assert not hasattr(app.state, "tracer_provider")
                assert app.title == settings.application.title
                assert app.openapi()["info"]["title"] == settings.application.title
                assert not settings.database_path.exists()
                assert not settings.frontend_dir.exists()
                assert not settings.logging.directory.exists()
                asyncio.run(check_uninitialized_factory())
                try:
                    get_tracer_provider()
                except RuntimeError as exc:
                    assert "not initialized" in str(exc)
                else:
                    raise AssertionError("Provider available without lifespan")
                assert "opentelemetry.sdk.trace" not in sys.modules
            """),
        ],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(config)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (service_project / ".run").exists()


@pytest.mark.anyio
async def test_lifespan_uses_fixed_process_settings_and_closes_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = settings_for(tmp_path)
    config.bind_settings(configuration)
    application = create_app()
    assert not hasattr(application.state, "tracer_provider")
    original_create = telemetry_provider._create_tracer_provider
    shutdown = Mock()

    def create_provider() -> TracerProvider:
        provider = original_create()
        shutdown.side_effect = provider.shutdown
        monkeypatch.setattr(provider, "shutdown", shutdown)
        return provider

    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    assert not configuration.logging.directory.exists()
    try:
        await asyncio.to_thread(upgrade_database)
        async with application.router.lifespan_context(application):
            assert config.get_settings() is configuration
            assert not hasattr(application.state, "settings")
            assert (configuration.logging.directory / configuration.logging.filename).is_file()
            application_module.logger.info("lifespan-probe {}", configuration.database_path)
            shutdown.assert_not_called()
            assert not hasattr(application.state, "session_factory")
            async with asynccontextmanager(get_session)() as session:
                databases = await session.execute(text("PRAGMA database_list"))
                database_file = next(
                    row["file"] for row in databases.mappings() if row["name"] == "main"
                )
                assert Path(database_file).resolve() == configuration.database_path
        shutdown.assert_called_once_with()
        log = configuration.logging.directory / configuration.logging.filename
        assert f"lifespan-probe {configuration.database_path}" in log.read_text()
        with operation_lock(configuration.database_path):
            pass
    finally:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer_provider()


@pytest.mark.anyio
async def test_lifespan_initializes_logging_before_frontend_check(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.serve_frontend = True
    application = create_app()
    log = settings.logging.directory / settings.logging.filename
    assert not settings.logging.directory.exists()
    original_check = application_module.check_frontend_directory

    def check_frontend() -> None:
        assert log.is_file()
        application_module.logger.info("frontend-startup-check-probe")
        original_check()

    monkeypatch.setattr(application_module, "check_frontend_directory", check_frontend)
    with pytest.raises(RuntimeError, match="Frontend"):
        async with application.router.lifespan_context(application):
            pytest.fail("Application started without frontend artifacts")
    assert "frontend-startup-check-probe" in log.read_text()


@pytest.mark.anyio
async def test_logging_initialization_failure_never_creates_provider_and_completes_logs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app()
    original_complete = application_module.logger.complete

    async def complete_logging() -> None:
        await original_complete()

    complete = AsyncMock(side_effect=complete_logging)
    configure = Mock(side_effect=OSError("logging unavailable"))
    engine = Mock()
    create_provider = Mock(side_effect=AssertionError("Provider initialized before logging"))
    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    monkeypatch.setattr(application_module, "configure_logging", configure)
    monkeypatch.setattr(application_module, "create_database_engine", engine)
    monkeypatch.setattr(application_module, "logger", SimpleNamespace(complete=complete))
    with pytest.raises(OSError, match="logging unavailable"):
        async with application.router.lifespan_context(application):
            pytest.fail("Application started after logging initialization failed")
    create_provider.assert_not_called()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()
    complete.assert_awaited_once_with()
    engine.assert_not_called()
    assert not settings.logging.directory.exists()


@pytest.mark.anyio
async def test_provider_initialization_failure_completes_logs_without_database_resources(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app()
    original_complete = application_module.logger.complete

    async def complete_logging() -> None:
        await original_complete()

    complete = AsyncMock(side_effect=complete_logging)
    create_provider = Mock(side_effect=RuntimeError("SDK unavailable"))
    engine = Mock(side_effect=AssertionError("Database initialized after provider failure"))
    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    monkeypatch.setattr(application_module, "create_database_engine", engine)
    monkeypatch.setattr(application_module, "logger", SimpleNamespace(complete=complete))
    with pytest.raises(RuntimeError, match="SDK unavailable"):
        async with application.router.lifespan_context(application):
            pytest.fail("Application started without provider")
    complete.assert_awaited_once_with()
    engine.assert_not_called()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()
    with pytest.raises(RuntimeError, match="not initialized"):
        async with asynccontextmanager(get_session)():
            pytest.fail("Session available after provider failure")


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("stage", ["startup", "shutdown"])
async def test_lifespan_failure_closes_resources_in_order(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
    stage: str,
) -> None:
    application = create_app()
    engine = create_database_engine()
    original_dispose = engine.dispose
    original_create = telemetry_provider._create_tracer_provider
    original_shutdown = None
    original_complete = application_module.logger.complete
    original_revision = application_module.check_database_revision
    closed = []

    async def dispose(actual_engine: AsyncEngine) -> None:
        assert actual_engine is engine
        with pytest.raises(RuntimeError, match="not initialized"):
            async with asynccontextmanager(get_session)():
                pytest.fail("Factory retained while disposing the engine")
        closed.append("factory")
        with pytest.raises(ServiceError, match="in progress"):
            with operation_lock(settings.database_path):
                pytest.fail("Database lock released before engine disposal")
        await original_dispose()
        closed.append("engine")

    def shutdown() -> None:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer_provider()
        with operation_lock(settings.database_path):
            pass
        assert original_shutdown is not None
        original_shutdown()
        closed.append("provider")

    async def complete_logging() -> None:
        await original_complete()
        closed.append("logs")

    async def fail_revision(actual_engine: AsyncEngine) -> None:
        assert actual_engine is engine
        if stage == "startup":
            raise failure("lifecycle probe")
        await original_revision(actual_engine)

    shutdown_mock = Mock(side_effect=shutdown)

    def create_provider() -> TracerProvider:
        nonlocal original_shutdown
        provider = original_create()
        original_shutdown = provider.shutdown
        monkeypatch.setattr(provider, "shutdown", shutdown_mock)
        return provider

    complete_mock = AsyncMock(side_effect=complete_logging)
    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    monkeypatch.setattr(application_module, "logger", SimpleNamespace(complete=complete_mock))
    monkeypatch.setattr(application_module, "create_database_engine", lambda: engine)
    monkeypatch.setattr(application_module, "check_database_revision", fail_revision)

    with pytest.raises(failure, match="lifecycle probe"):
        async with application.router.lifespan_context(application):
            assert stage == "shutdown"
            async with asynccontextmanager(get_session)() as session:
                assert session.bind is engine
            raise failure("lifecycle probe")

    shutdown_mock.assert_called_once_with()
    complete_mock.assert_awaited_once_with()
    assert closed == ["factory", "engine", "provider", "logs"]
    with operation_lock(settings.database_path):
        pass
