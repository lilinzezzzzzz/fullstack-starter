"""为 FastAPI 原生 telemetry 构建只维护上下文的本地 SDK provider。"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from app.telemetry.environment import configure_telemetry_environment

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

_provider: TracerProvider | None = None


def _create_tracer_provider() -> TracerProvider:
    # 遥测包入口保持轻量，配置模块只在实际构建 provider 时导入。
    from app.config import settings

    configure_telemetry_environment()

    # SDK 会在导入时创建部分默认对象；必须先完成 TOML 环境桥接。
    from opentelemetry import propagate
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanLimits, SynchronousMultiSpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    telemetry = settings.telemetry
    # 显式替换全局 propagator，避免模块缓存保留先前的外部选择。
    propagate.set_global_textmap(
        {"tracecontext": TraceContextTextMapPropagator()}[telemetry.propagators]
    )
    return TracerProvider(
        sampler={"always_off": ALWAYS_OFF}[telemetry.sampler],
        id_generator={"random": RandomIdGenerator()}[telemetry.id_generator],
        # 直接构造 Resource，避免 Resource.create() 自动运行环境探测器。
        resource=Resource(
            {
                "service.name": settings.application.title,
                "service.version": settings.application.version,
            }
        ),
        span_limits=SpanLimits(**telemetry.span_limits.model_dump()),
        active_span_processor=SynchronousMultiSpanProcessor(),
        meter_provider=NoOpMeterProvider(),
        shutdown_on_exit=telemetry.shutdown_on_exit,
    )


def get_tracer_provider() -> TracerProvider:
    """取得当前作用域的真实 provider；不隐式创建 SDK 资源。"""
    provider = _provider
    if provider is None:
        raise RuntimeError("Tracer provider is not initialized; enter lifespan first")
    return provider


@contextmanager
def tracer_provider_scope() -> Generator[TracerProvider]:
    """由 lifespan 创建、发布并关闭真实 provider，异常和取消同样清除引用。"""
    global _provider
    if _provider is not None:
        raise RuntimeError("Tracer provider is already initialized")
    provider: TracerProvider | None = None
    try:
        provider = _create_tracer_provider()
        _provider = provider
        yield provider
    finally:
        _provider = None
        if provider is not None:
            provider.shutdown()
