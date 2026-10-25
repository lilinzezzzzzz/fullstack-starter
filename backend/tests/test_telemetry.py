import pytest
from fastapi.telemetry import _asgi, _runtime
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
        assert client.get("/api/v1/hello").status_code == 200
        assert client.get("/api/missing").status_code == 404
