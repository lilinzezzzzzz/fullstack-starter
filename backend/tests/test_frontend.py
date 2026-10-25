from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def web_client(settings: Settings) -> Iterator[TestClient]:
    settings.serve_frontend = True
    settings.frontend_dir.mkdir()
    (settings.frontend_dir / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><title>Hello</title><main>Welcome</main></html>'
    )
    assets = settings.frontend_dir / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('hello')")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


def test_serves_build_and_deep_link(web_client: TestClient) -> None:
    assert "Welcome" in web_client.get("/").text
    deep_link = web_client.get("/welcome", headers={"accept": "text/html"})
    assert deep_link.status_code == 200
    assert "Welcome" in deep_link.text
    assert deep_link.headers["cache-control"] == "no-cache"
    assert web_client.get("/assets/app.js").status_code == 200
    head = web_client.head("/welcome", headers={"accept": "text/html"})
    assert head.status_code == 200
    assert head.content == b""


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/missing",
        "/assets/missing.js",
        "/missing.css",
        "/data/app.sqlite3",
        "/.data/app.sqlite3",
        "/.env",
    ],
)
def test_api_and_file_errors_do_not_become_html(web_client: TestClient, path: str) -> None:
    response = web_client.get(path, headers={"accept": "text/html"})
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_non_html_navigation_does_not_use_fallback(web_client: TestClient) -> None:
    response = web_client.get("/welcome", headers={"accept": "application/json"})
    assert response.status_code == 404


def test_same_origin_module_requests_are_allowed(web_client: TestClient) -> None:
    response = web_client.get("/assets/app.js", headers={"origin": "http://127.0.0.1"})
    assert response.status_code == 200


def test_encoded_hidden_paths_are_not_exposed(web_client: TestClient) -> None:
    response = web_client.get("/%2e%2e/%2eenv", headers={"accept": "text/html"})
    assert response.status_code == 404


def test_missing_frontend_has_actionable_startup_error(settings: Settings) -> None:
    settings.serve_frontend = True
    with pytest.raises(RuntimeError, match="pnpm --dir frontend build"):
        with TestClient(create_app(settings), base_url="http://127.0.0.1"):
            pass


def test_api_only_mode_needs_no_build(tmp_path: Path, settings: Settings) -> None:
    settings.frontend_dir = tmp_path / "never-built"
    settings.serve_frontend = False
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/hello").status_code == 200
        assert client.get("/").status_code == 404
    assert not settings.frontend_dir.exists()
