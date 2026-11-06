"""为 FastAPI 原生 telemetry 构建只维护上下文的本地 SDK provider。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.telemetry.environment import configure_telemetry_environment

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

    from app.config import Settings


def new_tracer_provider(settings: Settings) -> TracerProvider:
    configure_telemetry_environment(settings.telemetry)

    # SDK 会在导入时创建部分默认对象；必须先完成 TOML 环境桥接。
    from opentelemetry import propagate
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanLimits, SynchronousMultiSpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    config = settings.telemetry
    # 显式替换全局 propagator，避免模块缓存保留先前的外部选择。
    propagate.set_global_textmap(
        {"tracecontext": TraceContextTextMapPropagator()}[config.propagators]
    )
    return TracerProvider(
        sampler={"always_off": ALWAYS_OFF}[config.sampler],
        id_generator={"random": RandomIdGenerator()}[config.id_generator],
        # 直接构造 Resource，避免 Resource.create() 自动运行环境探测器。
        resource=Resource(
            {
                "service.name": settings.application.title,
                "service.version": settings.application.version,
            }
        ),
        span_limits=SpanLimits(**config.span_limits.model_dump()),
        active_span_processor=SynchronousMultiSpanProcessor(),
        meter_provider=NoOpMeterProvider(),
        shutdown_on_exit=config.shutdown_on_exit,
    )
