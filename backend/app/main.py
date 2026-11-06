from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import router
from app.config import ClientSettings, Settings
from app.database import check_database_revision, create_database_engine
from app.errors import register_error_handlers
from app.frontend import FrontendFiles, check_frontend_directory
from app.logging_setup import configure_logging
from app.middleware import RequestMiddleware
from app.service_state import operation_lock
from app.telemetry import new_tracer_provider


def create_app(settings: Settings) -> FastAPI:
    tracer_provider = new_tracer_provider(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            configure_logging(settings.logging)
            if settings.serve_frontend:
                check_frontend_directory(settings.frontend_dir)
            with ExitStack() as runtime:
                engine = create_database_engine(settings)
                try:
                    runtime.enter_context(operation_lock(settings.database_path))
                    await check_database_revision(engine, settings)
                    application.state.session_factory = async_sessionmaker(
                        engine, expire_on_commit=False
                    )
                    yield
                finally:
                    await engine.dispose()
        finally:
            tracer_provider.shutdown()

    application = FastAPI(
        telemetry={
            "tracer_provider": tracer_provider,
            "tracing": settings.telemetry.tracing,
            "metrics": settings.telemetry.metrics,
            "logs": settings.telemetry.logs,
            "operation_spans": settings.telemetry.operation_spans,
            "auto_configure": settings.telemetry.auto_configure,
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
    application.state.tracer_provider = tracer_provider
    application.add_middleware(RequestMiddleware, settings=settings)
    register_error_handlers(application)
    application.include_router(router)
    original_openapi = application.openapi

    def openapi_with_client_schema():
        schema = original_openapi()
        # 公开的构建时配置复用生成的类型，不向浏览器暴露服务端配置值。
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
