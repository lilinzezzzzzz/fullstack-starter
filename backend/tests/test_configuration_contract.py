import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import load_settings
from app.database import create_database_engine, upgrade_database
from app.main import create_app
from tests.helpers import read_config, save_config, write_config


def configuration_paths(data: dict, prefix: tuple[str, ...] = ()):
    for key, value in data.items():
        path = (*prefix, key)
        yield path
        if isinstance(value, dict):
            yield from configuration_paths(value, path)


def test_every_configuration_field_is_required(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    original = read_config(path)
    for field_path in configuration_paths(original):
        incomplete = deepcopy(original)
        parent = incomplete
        for part in field_path[:-1]:
            parent = parent[part]
        del parent[field_path[-1]]
        save_config(path, incomplete)
        with pytest.raises(ValidationError) as error:
            load_settings(path)
        assert any(item["type"] == "missing" for item in error.value.errors()), field_path


@pytest.mark.parametrize("field", ["server.port", "client.request_timeout_seconds"])
def test_wrong_types_are_not_coerced_or_defaulted(tmp_path: Path, field: str) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    section, key = field.split(".")
    data[section][key] = "123"
    save_config(path, data)
    with pytest.raises(ValidationError):
        load_settings(path)


def test_legacy_json_is_not_an_implicit_fallback(tmp_path: Path) -> None:
    (tmp_path / "app.json").write_text('{"data_dir": "wrong-directory"}')
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "app.toml")
    with pytest.raises(ValueError, match=".toml"):
        load_settings(tmp_path / "app.json")


def test_non_finite_timeout_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["client"]["request_timeout_seconds"] = float("inf")
    save_config(path, data)
    with pytest.raises(ValidationError):
        load_settings(path)


def test_zero_and_false_are_explicit_values_not_missing_values(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["client"].update(
        query_stale_seconds=0.0,
        query_cache_seconds=0.0,
        query_retry_attempts=0,
        refetch_on_mount=False,
        retry_network_errors=False,
    )
    data["logging"]["request_logging"] = False
    save_config(path, data)
    settings = load_settings(path)
    assert settings.client.query_stale_seconds == 0
    assert settings.client.query_cache_seconds == 0
    assert settings.client.query_retry_attempts == 0
    assert settings.client.refetch_on_mount is False
    assert settings.client.retry_network_errors is False
    assert settings.logging.request_logging is False


def test_documentation_and_metadata_are_driven_by_file(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["application"].update(
        title="configured-project", version="2.3.4", docs_enabled=False, redoc_enabled=False
    )
    data["serve_frontend"] = True
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><body>Hello</body></html>")
    save_config(path, data)
    settings = load_settings(path)
    upgrade_database(settings)
    app = create_app(settings)
    assert app.openapi()["info"] == {"title": "configured-project", "version": "2.3.4"}
    schema = app.openapi()["components"]["schemas"]["ClientSettings"]
    assert set(schema["required"]) == set(schema["properties"])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/docs", headers={"accept": "text/html"}).status_code == 404
        assert client.get("/api/v1/hello").json() == {"message": "Hello, configured-project!"}


@pytest.mark.anyio
async def test_journal_and_durability_are_driven_by_file(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["database"].update(journal_mode="DELETE", synchronous="EXTRA")
    save_config(path, data)
    settings = load_settings(path)
    await asyncio.to_thread(upgrade_database, settings)
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar() == "delete"
            assert (await connection.exec_driver_sql("PRAGMA synchronous")).scalar() == 3
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_pool_limits_are_driven_by_file(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["database"].update(pool_size=2, max_overflow=0, pool_timeout_seconds=0.05)
    save_config(path, data)
    settings = load_settings(path)
    await asyncio.to_thread(upgrade_database, settings)
    engine = create_database_engine(settings)
    try:
        async with engine.connect(), engine.connect():
            with pytest.raises(PoolTimeoutError):
                await engine.connect()
    finally:
        await engine.dispose()


def test_public_output_cannot_contain_private_storage(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["frontend_dir"] = data["data_dir"]
    save_config(path, data)
    with pytest.raises(ValidationError, match="private data"):
        load_settings(path)
