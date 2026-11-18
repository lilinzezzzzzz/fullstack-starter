from collections.abc import AsyncGenerator
from contextlib import ExitStack, asynccontextmanager

from fastapi import APIRouter, FastAPI
from loguru import logger

from app.config import settings
from app.infra import errors
from app.infra.database import (
    check_database_revision,
    create_database_engine,
    session_factory_scope,
)
from app.infra.frontend import FrontendFiles, check_frontend_directory
from app.infra.logging import configure_logging
from app.infra.middleware import RequestMiddleware
from app.routers import health, hello
from app.schemas.common import ErrorResponse
from app.telemetry import tracer_provider_scope
from app.telemetry.adapter import TracerProviderAdapter
from app.telemetry.environment import configure_telemetry_environment
from app.utils.database_lock import operation_lock


def create_app() -> FastAPI:
    # 导入的代理保持身份不变，只在构建执行阶段读取已选配置。
    configure_telemetry_environment()
    application = FastAPI(
        telemetry={
            "tracer_provider": TracerProviderAdapter(),
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
    application.add_middleware(RequestMiddleware)
    errors.register_error_handlers(application)
    _register_api_routes(application)
    _mount_frontend(application)
    return application


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    try:
        configure_logging()
        with tracer_provider_scope():
            if settings.serve_frontend:
                check_frontend_directory()
            with ExitStack() as runtime:
                engine = create_database_engine()
                try:
                    runtime.enter_context(operation_lock(settings.database_path))
                    await check_database_revision(engine)
                    with session_factory_scope(engine):
                        yield
                finally:
                    # 连接清理完成后再退出 runtime，释放数据库操作锁。
                    await engine.dispose()
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


def _mount_frontend(application: FastAPI) -> None:
    if not settings.serve_frontend:
        return
    application.mount("/", FrontendFiles(), name="frontend")
