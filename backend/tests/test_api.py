import pytest
from fastapi import Query
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from app.config import Settings
from app.errors import AppError
from app.main import create_app
from app.services import hello


def test_hello(client: TestClient, settings: Settings) -> None:
    response = client.get("/api/v1/hello")
    assert response.status_code == 200
    assert response.json() == {"message": f"Hello, {settings.application.title}!"}
    assert response.headers["cache-control"] == "no-store"


def test_health_checks_database(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}


def test_method_not_allowed_preserves_allow_header(client: TestClient) -> None:
    response = client.post("/api/v1/hello")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json()["code"] == "HTTP_405"


@pytest.mark.parametrize(
    ("status", "name", "value"),
    [(401, "WWW-Authenticate", "Bearer"), (429, "Retry-After", "30")],
)
def test_http_error_preserves_protocol_headers_without_overriding_safety_headers(
    settings: Settings, status: int, name: str, value: str
) -> None:
    app = create_app(settings)

    @app.get("/api/protocol-error")
    def fail() -> None:
        raise HTTPException(
            status,
            headers={name: value, "Cache-Control": "public", "X-Request-ID": "untrusted"},
        )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/protocol-error")
    assert response.status_code == status
    assert response.headers[name] == value
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] != "untrusted"


def test_unknown_api_has_uniform_error(client: TestClient) -> None:
    response = client.get("/api/not-found", headers={"accept": "text/html"})
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers["x-request-id"]


def test_request_ids_are_generated_per_request(client: TestClient) -> None:
    first = client.get("/api/v1/hello", headers={"x-request-id": "untrusted-id"})
    second = client.get("/api/v1/hello")
    assert first.headers["x-request-id"] != "untrusted-id"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({"host": "untrusted.example"}, 400, "INVALID_HOST"),
        ({"origin": "https://untrusted.example"}, 403, "INVALID_ORIGIN"),
        ({"origin": "null"}, 403, "INVALID_ORIGIN"),
        ({"sec-fetch-site": "cross-site"}, 403, "INVALID_ORIGIN"),
    ],
)
def test_local_access_boundaries(
    client: TestClient, headers: dict[str, str], status: int, code: str
) -> None:
    response = client.get("/api/v1/hello", headers=headers)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_vite_origin_is_allowed(client: TestClient, settings: Settings) -> None:
    host = f"[{settings.vite.host}]" if ":" in settings.vite.host else settings.vite.host
    origin = f"http://{host}:{settings.vite.port}"
    response = client.get("/api/v1/hello", headers={"origin": origin})
    assert response.status_code == 200


def test_same_origin_is_allowed_on_custom_port(settings: Settings) -> None:
    with TestClient(create_app(settings), base_url="http://127.0.0.1:12345") as client:
        response = client.get("/api/v1/hello", headers={"origin": "http://127.0.0.1:12345"})
    assert response.status_code == 200


def test_application_and_validation_errors(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/api/validation")
    def validate(number: int = Query(ge=1)) -> int:
        return number

    @app.get("/api/application-error")
    def fail() -> None:
        raise AppError("EXAMPLE_ERROR", "Example error", 409)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        invalid = client.get("/api/validation?number=0")
        assert invalid.status_code == 422
        assert invalid.json()["details"][0]["field"] == "query.number"
        assert "input" not in invalid.json()["details"][0]
        failure = client.get("/api/application-error")
        assert failure.status_code == 409
        assert failure.json()["code"] == "EXAMPLE_ERROR"


def test_unexpected_error_is_safe(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_application_title: str) -> None:
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(hello, "say_hello", fail)
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/v1/hello")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "private implementation" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert response.headers["x-request-id"] in contents
    assert "Unhandled request error" in contents
