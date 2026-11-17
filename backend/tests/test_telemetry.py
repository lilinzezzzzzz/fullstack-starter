import asyncio
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
from opentelemetry.sdk.trace import Tracer, TracerProvider
from pydantic import ValidationError

from app import config as app_config
from app.application import create_app
from app.config import BACKEND_ROOT, Settings, load_settings
from app.telemetry import get_tracer_provider, tracer_provider_scope
from app.telemetry import provider as telemetry_provider
from app.telemetry.adapter import TracerProviderAdapter
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
                import app.infra
                from app.telemetry import get_tracer_provider, tracer_provider_scope
                from app.telemetry.environment import clear_telemetry_environment

                assert callable(get_tracer_provider)
                assert callable(tracer_provider_scope)
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
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/hello").status_code == 200
        assert client.get("/api/health").status_code == 200


def test_cached_adapter_tracer_follows_active_scope_and_forwards_metadata(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TracerProviderAdapter()
    tracer = adapter.get_tracer("adapter-probe", "2.0", "https://schema.test", {"scope": "probe"})
    with pytest.raises(RuntimeError, match="not initialized"):
        tracer.start_span("before startup")
    with pytest.raises(RuntimeError, match="not initialized"):
        tracer.start_as_current_span("before startup")
    old_lookup = None
    old_count = None
    for _ in range(2):
        with tracer_provider_scope() as provider:
            lookup = Mock(wraps=provider.get_tracer)
            shutdown = Mock(wraps=provider.shutdown)
            monkeypatch.setattr(provider, "get_tracer", lookup)
            monkeypatch.setattr(provider, "shutdown", shutdown)
            with pytest.raises(RuntimeError, match="already initialized"):
                with tracer_provider_scope():
                    pytest.fail("Duplicate provider initialization succeeded")
            assert get_tracer_provider() is provider
            span = tracer.start_span("unattached")
            assert span.get_span_context().is_valid
            assert not span.is_recording()
            span.end()
            with tracer.start_as_current_span("outer") as outer:
                with pytest.raises(ValueError, match="context probe"):
                    with tracer.start_as_current_span("inner") as inner:
                        assert trace.get_current_span() is inner
                        raise ValueError("context probe")
                assert trace.get_current_span() is outer
            assert not trace.get_current_span().get_span_context().is_valid
            lookup.assert_called_with(
                "adapter-probe",
                "2.0",
                schema_url="https://schema.test",
                attributes={"scope": "probe"},
            )
            if old_lookup is not None:
                assert old_lookup.call_count == old_count
            old_lookup, old_count = lookup, lookup.call_count
        shutdown.assert_called_once_with()
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer_provider()
        with pytest.raises(RuntimeError, match="not initialized"):
            tracer.start_span("after shutdown")


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_provider_scope_clears_on_exception_or_cancellation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    with pytest.raises(failure, match="provider scope probe"):
        with tracer_provider_scope() as provider:
            shutdown = Mock(wraps=provider.shutdown)
            monkeypatch.setattr(provider, "shutdown", shutdown)
            raise failure("provider scope probe")
    shutdown.assert_called_once_with()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()


def test_provider_creation_failure_does_not_publish_resource(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        telemetry_provider,
        "_create_tracer_provider",
        Mock(side_effect=RuntimeError("SDK unavailable")),
    )
    with pytest.raises(RuntimeError, match="SDK unavailable"):
        with tracer_provider_scope():
            pytest.fail("Failed provider became available")
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()


def test_provider_shutdown_failure_still_clears_module_reference(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_shutdown = None
    try:
        with pytest.raises(RuntimeError, match="shutdown probe"):
            with tracer_provider_scope() as provider:
                original_shutdown = provider.shutdown

                def failed_shutdown() -> None:
                    with pytest.raises(RuntimeError, match="not initialized"):
                        get_tracer_provider()
                    raise RuntimeError("shutdown probe")

                monkeypatch.setattr(provider, "shutdown", failed_shutdown)
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer_provider()
    finally:
        if original_shutdown is not None:
            original_shutdown()


def test_openapi_cli_never_creates_sdk_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from entrypoints import cli

    config_file = write_config(tmp_path, serve_frontend=True)
    create_provider = Mock(side_effect=AssertionError("SDK created during OpenAPI export"))
    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    app_config.bind_settings(load_settings(config_file))
    monkeypatch.setattr(sys, "argv", ["cli", "--config", str(config_file), "export-openapi"])
    cli.main()
    assert (
        json.loads(capsys.readouterr().out)["info"]["title"]
        == app_config.settings.application.title
    )
    create_provider.assert_not_called()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()
    assert not app_config.settings.data_dir.exists()
    assert not app_config.settings.frontend_dir.exists()
    assert not app_config.settings.logging.directory.exists()


def test_fastapi_cached_tracer_uses_new_sdk_provider_for_each_lifespan(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_create = telemetry_provider._create_tracer_provider
    lookups = []
    shutdowns = []

    def create_provider() -> TracerProvider:
        provider = original_create()
        lookup = Mock(wraps=provider.get_tracer)
        shutdown = Mock(wraps=provider.shutdown)
        monkeypatch.setattr(provider, "get_tracer", lookup)
        monkeypatch.setattr(provider, "shutdown", shutdown)
        lookups.append(lookup)
        shutdowns.append(shutdown)
        return provider

    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    application = create_app()
    assert not lookups
    old_count = None
    for index in range(2):
        with TestClient(application, base_url="http://127.0.0.1") as client:
            response = client.get("/api/v1/hello")
            assert response.status_code == 200
            response_trace_id(response.headers)
            assert lookups[index].call_count > 0
            if index:
                assert lookups[0].call_count == old_count
            old_count = lookups[index].call_count
        shutdowns[index].assert_called_once_with()
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer_provider()


def test_global_providers_are_not_used(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    class UnexpectedProvider:
        def get_tracer(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global tracer provider")

        def get_meter(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global meter provider")

        def get_logger(self, *args: object, **kwargs: object) -> None:
            pytest.fail("FastAPI used a global logger provider")

    provider = UnexpectedProvider()

    def unexpected_global_replacement(*args: object, **kwargs: object) -> None:
        pytest.fail("Application replaced a global OpenTelemetry provider")

    monkeypatch.setattr(_asgi.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(_asgi.metrics, "get_meter_provider", lambda: provider)
    monkeypatch.setattr(_asgi._logs, "get_logger_provider", lambda: provider)
    monkeypatch.setattr(_asgi.trace, "set_tracer_provider", unexpected_global_replacement)
    monkeypatch.setattr(_asgi.metrics, "set_meter_provider", unexpected_global_replacement)
    monkeypatch.setattr(_asgi._logs, "set_logger_provider", unexpected_global_replacement)
    with TestClient(
        create_app(), base_url="http://127.0.0.1", raise_server_exceptions=False
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
                from app import config as app_config
                from app.application import create_app
                from app.telemetry import tracer_provider_scope
                from fastapi.testclient import TestClient
                from opentelemetry import trace
                from migrations.operations import upgrade_database
                from tests.helpers import response_trace_id
                from opentelemetry.trace.propagation.tracecontext import (
                    TraceContextTextMapPropagator,
                )

                settings = app_config.load_settings(sys.argv[1])
                app_config.bind_settings(settings)
                app = create_app()
                assert not hasattr(app.state, "tracer_provider")
                propagator = TraceContextTextMapPropagator()
                identifiers = []
                assert not settings.database_path.exists()
                assert not settings.frontend_dir.exists()
                schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
                assert schema["properties"].get("trace_id")
                with tracer_provider_scope() as provider:
                    tracer = provider.get_tracer("configuration-probe")
                    for carrier in ({}, {"traceparent": "invalid"}):
                        parent = propagator.extract(carrier)
                        with tracer.start_as_current_span("probe", context=parent) as span:
                            context = span.get_span_context()
                            assert context.is_valid and not span.is_recording()
                            identifiers.append(trace.format_trace_id(context.trace_id))
                    assert len(set(identifiers)) == 2
                    resource = dict(provider.resource.attributes)
                upgrade_database()
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
                    "resource": resource,
                }))
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
    app_config.bind_settings(settings)
    for name, value in POISONED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    original_limits = sdk_trace.SpanLimits
    limits = Mock(wraps=original_limits)
    monkeypatch.setattr(sdk_trace, "SpanLimits", limits)
    app = create_app()
    limits.assert_not_called()
    with tracer_provider_scope() as provider:
        assert dict(provider.resource.attributes) == {
            "service.name": "configured-service",
            "service.version": "2.0.1",
        }
        limits.assert_called_once_with(**data["telemetry"]["span_limits"])
        assert os.environ["OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS"] == "POST"
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
        assert app._native_telemetry._known_methods == frozenset({"POST"})
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()


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
    app = create_app()

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
    settings.serve_frontend = startup_failure
    app = create_app()
    original_create = telemetry_provider._create_tracer_provider
    shutdown = Mock()

    def create_provider() -> TracerProvider:
        provider = original_create()
        shutdown.side_effect = provider.shutdown
        monkeypatch.setattr(provider, "shutdown", shutdown)
        return provider

    monkeypatch.setattr(telemetry_provider, "_create_tracer_provider", create_provider)
    if startup_failure:
        with pytest.raises(RuntimeError, match="Frontend"):
            with TestClient(app, base_url="http://127.0.0.1"):
                pass
    else:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert client.get("/api/health").status_code == 200
    shutdown.assert_called_once_with()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_tracer_provider()


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
