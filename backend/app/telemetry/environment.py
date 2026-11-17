"""隔离外部遥测环境，并将已校验的 TOML 值桥接到仅支持环境变量的入口。"""

import os


def clear_telemetry_environment() -> None:
    """在第三方遥测模块导入前丢弃进程继承的遥测设置，不记录其值。"""
    for name in tuple(os.environ):
        if name.startswith(("OTEL_", "FASTAPI_OTEL_")):
            del os.environ[name]


def configure_telemetry_environment() -> None:
    """在应用构建和 provider 初始化阶段写入白名单，不在请求期间改环境。"""
    # 此模块也由 app 包入口使用；清理外部环境前不能导入配置及第三方库。
    from app.config import settings

    telemetry = settings.telemetry
    clear_telemetry_environment()
    os.environ.update(
        {
            "OTEL_SDK_DISABLED": str(telemetry.sdk_disabled).lower(),
            "OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED": str(
                telemetry.internal_metrics_enabled
            ).lower(),
            "OTEL_PYTHON_CONTEXT": telemetry.context,
            "OTEL_PROPAGATORS": telemetry.propagators,
            "OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS": ",".join(telemetry.known_methods),
            "FASTAPI_OTEL_AUTO_CONFIGURE": str(telemetry.auto_configure).lower(),
        }
    )
