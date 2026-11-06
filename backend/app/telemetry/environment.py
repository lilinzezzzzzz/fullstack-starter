"""隔离外部遥测环境，并将已校验的 TOML 值桥接到仅支持环境变量的入口。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import TelemetrySettings


def clear_telemetry_environment() -> None:
    """在第三方遥测模块导入前丢弃进程继承的遥测设置，不记录其值。"""
    for name in tuple(os.environ):
        if name.startswith(("OTEL_", "FASTAPI_OTEL_")):
            del os.environ[name]


def configure_telemetry_environment(settings: TelemetrySettings) -> None:
    """仅在应用构建阶段写入固定白名单，所有值均来自完整 TOML 配置。"""
    clear_telemetry_environment()
    os.environ.update(
        {
            "OTEL_SDK_DISABLED": str(settings.sdk_disabled).lower(),
            "OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED": str(
                settings.internal_metrics_enabled
            ).lower(),
            "OTEL_PYTHON_CONTEXT": settings.context,
            "OTEL_PROPAGATORS": settings.propagators,
            "OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS": ",".join(settings.known_methods),
            "FASTAPI_OTEL_AUTO_CONFIGURE": str(settings.auto_configure).lower(),
        }
    )
