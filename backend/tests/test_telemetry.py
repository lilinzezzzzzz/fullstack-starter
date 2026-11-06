import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import Mock

import pytest
from fastapi.telemetry import _asgi, _runtime
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import Tracer
from pydantic import ValidationError

from app.config import BACKEND_ROOT, Settings, load_settings
from app.main import create_app
from tests.helpers import read_config, response_trace_id, save_config, write_config

POISONED_ENVIRONMENT = {
    "FASTAPI_OTEL_AUTO_CONFIGURE": "true",
    "OTEL_SDK_DISABLED": "true",
    "OTEL_TRACES_SAMPLER": "always_on",
    "OTEL_PROPAGATORS": "not-installed-propagator",
    "OTEL_PYTHON_CONTEXT": "not-installed-context",
    "OTEL_SERVICE_NAME": "external-service",
    "OTEL_RESOURCE_ATTRIBUTES": "external.marker=must-not-be-used",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1",
    "OTEL_EXPORTER_OTLP_HEADERS": "fake-test-header=must-not-be-inherited",
    "OTEL_PYTHON_TRACER_PROVIDER": "not-installed-provider",
    "OTEL_PYTHON_METER_PROVIDER": "not-installed-provider",
    "OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED": "true",
    "OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS": "EXTERNAL",
    "OTEL_ATTRIBUTE_COUNT_LIMIT": "not-an-integer",
    "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "not-an-integer",
    "OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT": "not-an-integer",
    "OTEL_EXPERIMENTAL_RESOURCE_DETECTORS": "not-installed-detector",
    "OTEL_UNKNOWN_EXTERNAL_SETTING": "must-not-be-inherited",
}


def test_telemetry_package_keeps_environment_cleanup_before_third_party_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import os
                import sys
                import app
                from app.telemetry import new_tracer_provider
                from app.telemetry.environment import clear_telemetry_environment

                assert callable(new_tracer_provider)
                assert callable(clear_telemetry_environment)
                assert "app.config" not in sys.modules
                assert not any(name.startswith(("opentelemetry", "fastapi", "pydantic"))
                               for name in sys.modules)
                assert not any(name.startswith(("OTEL_", "FASTAPI_OTEL_"))
                               for name in os.environ)
                print("lightweight telemetry package verified")
                """),
        ],
        cwd=BACKEND_ROOT,
        env={**os.environ, **POISONED_ENVIRONMENT},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "lightweight telemetry package verified"
    assert result.stderr == ""


def test_environment_cannot_enable_automatic_telemetry(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    def unexpected_exporter_setup(*args: object) -> None:
        pytest.fail("FastAPI attempted to configure an exporter from the environment")

    monkeypatch.setattr(_runtime, "_export_endpoint", unexpected_exporter_setup)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/hello").status_code == 200
        assert client.get("/api/health").status_code == 200


def test_global_providers_are_not_used(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    class UnexpectedProvider:
        def get_tracer(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global tracer provider")

        def get_meter(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global meter provider")

        def get_logger(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global logger provider")

    provider = UnexpectedProvider()
    monkeypatch.setattr(_asgi.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(_asgi.metrics, "get_meter_provider", lambda: provider)
    monkeypatch.setattr(_asgi._logs, "get_logger_provider", lambda: provider)
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.get(
            "/api/v1/hello",
            headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
        )
        assert response.status_code == 200
        assert response_trace_id(response.headers) == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert client.get("/api/missing").status_code == 404


def test_fresh_process_ignores_environment_before_telemetry_imports(tmp_path: Path) -> None:
    config = write_config(tmp_path, data_dir=str(tmp_path / "missing-database"))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import json
                import os
                import sys
                from app.config import load_settings
                from app.main import create_app
                from fastapi.testclient import TestClient
                from opentelemetry import trace
                from migrations.operations import upgrade_database
                from tests.helpers import response_trace_id
                from opentelemetry.trace.propagation.tracecontext import (
                    TraceContextTextMapPropagator,
                )

                settings = load_settings(sys.argv[1])
                app = create_app(settings)
                provider = app.state.tracer_provider
                tracer = provider.get_tracer("configuration-probe")
                propagator = TraceContextTextMapPropagator()
                identifiers = []
                try:
                    for carrier in ({}, {"traceparent": "invalid"}):
                        parent = propagator.extract(carrier)
                        with tracer.start_as_current_span("probe", context=parent) as span:
                            context = span.get_span_context()
                            assert context.is_valid and not span.is_recording()
                            identifiers.append(trace.format_trace_id(context.trace_id))
                    assert len(set(identifiers)) == 2
                    assert not settings.database_path.exists()
                    assert not settings.frontend_dir.exists()
                    schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
                    assert schema["properties"].get("trace_id")
                    upgrade_database(settings)
                    with TestClient(app, base_url="http://127.0.0.1") as client:
                        generated = []
                        for headers in ({}, {"traceparent": "invalid"}):
                            response = client.get("/api/not-found", headers=headers)
                            assert response.status_code == 404
                            identifier = response_trace_id(response.headers)
                            assert len(identifier) == 32 and int(identifier, 16) != 0
                            assert response.json()["trace_id"] == identifier
                            generated.append(identifier)
                        assert len(set(generated)) == 2
                        response = client.get("/api/v1/hello", headers={
                            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
                        })
                        assert response.status_code == 200
                        assert response_trace_id(response.headers) == (
                            "4bf92f3577b34da6a3ce929d0e0e4736"
                        )
                    print(json.dumps({
                        "environment": {key: value for key, value in os.environ.items()
                                        if key.startswith(("OTEL_", "FASTAPI_OTEL_"))},
                        "resource": dict(provider.resource.attributes),
                    }))
                finally:
                    provider.shutdown()
                """),
            str(config),
        ],
        cwd=BACKEND_ROOT,
        env={**os.environ, **POISONED_ENVIRONMENT},
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["environment"] == {
        "OTEL_SDK_DISABLED": "false",
        "OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED": "false",
        "OTEL_PYTHON_CONTEXT": "contextvars_context",
        "OTEL_PROPAGATORS": "tracecontext",
        "OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS": (
            "CONNECT,DELETE,GET,HEAD,OPTIONS,PATCH,POST,PUT,QUERY,TRACE"
        ),
        "FASTAPI_OTEL_AUTO_CONFIGURE": "false",
    }
    application = read_config(config)["application"]
    assert data["resource"] == {
        "service.name": application["title"],
        "service.version": application["version"],
    }
    assert result.stderr == ""


def test_toml_controls_resource_limits_and_native_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk import trace as sdk_trace

    config = write_config(tmp_path)
    data = read_config(config)
    data["application"].update(title="configured-service", version="2.0.1")
    data["telemetry"]["known_methods"] = ["POST"]
    data["telemetry"]["span_limits"]["max_attributes"] = 7
    save_config(config, data)
    settings = load_settings(config)
    for name, value in POISONED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    original_limits = sdk_trace.SpanLimits
    limits = Mock(wraps=original_limits)
    monkeypatch.setattr(sdk_trace, "SpanLimits", limits)
    app = create_app(settings)
    try:
        assert dict(app.state.tracer_provider.resource.attributes) == {
            "service.name": "configured-service",
            "service.version": "2.0.1",
        }
        limits.assert_called_once_with(**data["telemetry"]["span_limits"])
        assert os.environ["OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS"] == "POST"
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
        assert app._native_telemetry._known_methods == frozenset({"POST"})
    finally:
        app.state.tracer_provider.shutdown()


def test_sdk_creates_context_without_recording_or_processors(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk.trace import _Span
    from opentelemetry.sdk.trace._tracer_metrics import TracerMetrics

    def unexpected_collection(*args: object, **kwargs: object) -> None:
        pytest.fail("Telemetry attempted to record spans or internal metrics")

    monkeypatch.setattr(_Span, "start", unexpected_collection)
    monkeypatch.setattr(TracerMetrics, "__init__", unexpected_collection)
    original_start = Tracer.start_span
    created = []

    def observe_start(self, *args, **kwargs):
        span = original_start(self, *args, **kwargs)
        created.append((kwargs["kind"], span.get_span_context(), span.is_recording()))
        return span

    monkeypatch.setattr(Tracer, "start_span", observe_start)
    app = create_app(settings)

    @app.get("/api/span-context")
    def observe() -> dict[str, object]:
        span = trace.get_current_span()
        context = span.get_span_context()
        return {
            "trace_id": trace.format_trace_id(context.trace_id),
            "span_id": trace.format_span_id(context.span_id),
            "recording": span.is_recording(),
        }

    with TestClient(app, base_url="http://127.0.0.1") as client:
        results = [client.get("/api/span-context").json()]
        for _ in range(2):
            results.append(
                client.get(
                    "/api/span-context",
                    headers={
                        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
                    },
                ).json()
            )
    assert all(
        kind == trace.SpanKind.SERVER and context.is_valid and not recording
        for kind, context, recording in created
    )
    assert len(created) == 3
    assert results[1]["trace_id"] == results[2]["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert len({item["span_id"] for item in results}) == 3
    assert all(not item["recording"] for item in results)


@pytest.mark.parametrize("startup_failure", [False, True])
def test_owned_provider_is_closed_on_lifespan_exit(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, startup_failure: bool
) -> None:
    app = create_app(settings.model_copy(update={"serve_frontend": startup_failure}))
    provider = app.state.tracer_provider
    shutdown = Mock(wraps=provider.shutdown)
    monkeypatch.setattr(provider, "shutdown", shutdown)
    if startup_failure:
        with pytest.raises(RuntimeError, match="Frontend"):
            with TestClient(app, base_url="http://127.0.0.1"):
                pass
    else:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert client.get("/api/health").status_code == 200
    shutdown.assert_called_once_with()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tracing", False),
        ("sdk_disabled", True),
        ("metrics", True),
        ("logs", True),
        ("operation_spans", True),
        ("auto_configure", True),
        ("internal_metrics_enabled", True),
        ("shutdown_on_exit", True),
        ("sampler", "always_on"),
        ("propagators", "baggage"),
        ("context", "external"),
        ("known_methods", []),
        ("sdk_disabled", 0),
    ],
)
def test_configuration_cannot_disable_context_or_enable_collection(
    tmp_path: Path, field: str, value: object
) -> None:
    config = write_config(tmp_path)
    data = read_config(config)
    data["telemetry"][field] = value
    save_config(config, data)
    with pytest.raises(ValidationError):
        load_settings(config)
