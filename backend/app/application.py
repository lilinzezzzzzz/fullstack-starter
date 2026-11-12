from collections.abc import AsyncGenerator
from contextlib import ExitStack, asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import ClientSettings, Settings
from app.infra import errors
from app.infra.database import check_database_revision, create_database_engine
from app.infra.frontend import FrontendFiles, check_frontend_directory
from app.infra.logging_setup import configure_logging
from app.infra.middleware import RequestMiddleware
from app.routers import health, hello
from app.schemas.common import ErrorResponse
from app.telemetry import new_tracer_provider
from app.utils.database_lock import operation_lock


def create_app(settings: Settings) -> FastAPI:
    tracer_provider = new_tracer_provider(settings)
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
        docs_url=settings.application.docs_url,
        redoc_url=settings.application.redoc_url,
        openapi_url=settings.application.openapi_url,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.tracer_provider = tracer_provider
    application.add_middleware(RequestMiddleware, settings=settings)
    errors.register_error_handlers(application)
    _register_api_routes(application)
    _configure_openapi(application)
    _mount_frontend(application, settings)
    return application


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = application.state.settings
    tracer_provider = application.state.tracer_provider
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
                # 连接清理完成后再退出 runtime，释放数据库操作锁。
                await engine.dispose()
    finally:
        try:
            tracer_provider.shutdown()
        finally:
            await logger.complete()


def _register_api_routes(application: FastAPI) -> None:
    api_router = APIRouter(
        prefix="/api",
        responses={
            400: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    api_router.include_router(health.router)
    api_router.include_router(hello.router)
    application.include_router(api_router)


def _configure_openapi(application: FastAPI) -> None:
    original_openapi = application.openapi

    def openapi_with_client_schema() -> dict[str, Any]:
        schema = original_openapi()
        # 公开的构建时配置复用生成的类型，不向浏览器暴露服务端配置值。
        schema["components"]["schemas"]["ClientSettings"] = ClientSettings.model_json_schema()
        return schema

    application.openapi = openapi_with_client_schema


def _mount_frontend(application: FastAPI, settings: Settings) -> None:
    if not settings.serve_frontend:
        return
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
