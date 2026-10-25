from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import router
from app.config import ClientSettings, Settings
from app.database import check_database_revision, create_database_engine
from app.errors import register_error_handlers
from app.frontend import FrontendFiles, check_frontend_directory
from app.logging_setup import configure_logging
from app.middleware import RequestMiddleware


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.logging)
        if settings.serve_frontend:
            check_frontend_directory(settings.frontend_dir)
        engine = create_database_engine(settings)
        try:
            await check_database_revision(engine, settings)
            application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
            yield
        finally:
            await engine.dispose()

    application = FastAPI(
        # Telemetry is an explicit project capability; the scaffold does not opt in.
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
        title=settings.application.title,
        version=settings.application.version,
        docs_url=settings.application.docs_path if settings.application.docs_enabled else None,
        redoc_url=settings.application.redoc_path if settings.application.redoc_enabled else None,
        openapi_url=settings.application.openapi_path
        if settings.application.openapi_enabled
        else None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.add_middleware(RequestMiddleware, settings=settings)
    register_error_handlers(application)
    application.include_router(router)
    original_openapi = application.openapi

    def openapi_with_client_schema():
        schema = original_openapi()
        # Public build-time settings share generated types, without publishing server values.
        schema["components"]["schemas"]["ClientSettings"] = ClientSettings.model_json_schema()
        return schema

    application.openapi = openapi_with_client_schema
    if settings.serve_frontend:
        application.mount(
            "/",
            FrontendFiles(
                directory=settings.frontend_dir,
                reserved_paths=[
                    settings.application.docs_path,
                    settings.application.redoc_path,
                    settings.application.openapi_path,
                ],
            ),
            name="frontend",
        )
    return application
