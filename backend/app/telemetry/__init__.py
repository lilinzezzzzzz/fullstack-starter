"""遥测包的轻量入口；真实 SDK provider 仅在生命周期作用域中创建。"""

from app.telemetry.provider import get_tracer_provider as get_tracer_provider
from app.telemetry.provider import tracer_provider_scope as tracer_provider_scope
