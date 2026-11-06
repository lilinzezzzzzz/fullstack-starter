import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

import tomli_w
from opentelemetry.trace import SpanContext, format_trace_id, get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.config import CONFIG_FILE, Settings, load_settings


def response_trace_context(headers: Mapping[str, str]) -> SpanContext:
    """校验响应使用完整 W3C 上下文，并保持采样关闭及无旧响应头。"""
    value = headers["traceparent"]
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", value)
    assert "x-trace-id" not in headers
    assert "x-request-id" not in headers
    context = TraceContextTextMapPropagator().extract({"traceparent": value})
    span_context = get_current_span(context).get_span_context()
    assert span_context.is_valid
    assert not span_context.trace_flags.sampled
    return span_context


def response_trace_id(headers: Mapping[str, str]) -> str:
    return format_trace_id(response_trace_context(headers).trace_id)


def read_config(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def save_config(path: Path, data: dict) -> None:
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def write_config(directory: Path, **overrides: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = read_config(CONFIG_FILE)
    data.update(
        data_dir=str(directory / "data"),
        frontend_dir=str(directory / "dist"),
        serve_frontend=False,
        frontend_clean_output=False,
        backup_directory=str(directory / "backups"),
        sqlite_timeout_seconds=0.05,
    )
    data["logging"]["directory"] = str(directory / "logs")
    data["service"]["pid_file"] = str(directory / "service.pid")
    data.update(overrides)
    path = directory / "settings.toml"
    save_config(path, data)
    return path


def settings_for(directory: Path, **overrides: object) -> Settings:
    return load_settings(write_config(directory, **overrides))
