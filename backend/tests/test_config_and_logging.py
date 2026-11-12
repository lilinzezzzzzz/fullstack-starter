import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger
from pydantic import ValidationError

from app.application import create_app
from app.config import PROJECT_ROOT, load_settings
from app.infra.logging_setup import configure_logging
from tests.helpers import read_config, response_trace_id, save_config, write_config


def test_environment_and_dotenv_do_not_override_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path)
    (tmp_path / ".env").write_text("APP_DATA_DIR=/not-the-configured-directory\n")
    monkeypatch.setenv("APP_DATA_DIR", "/not-the-configured-directory")
    monkeypatch.setenv("APP_SERVE_FRONTEND", "true")
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    settings = load_settings(config)
    assert settings.data_dir == tmp_path / "data"
    assert settings.serve_frontend is False
    assert settings.server.workers == 1


def test_all_paths_are_root_relative_and_database_filename_is_configurable(tmp_path: Path) -> None:
    config = write_config(tmp_path, data_dir=".data/custom", database_filename="custom.db")
    raw = read_config(config)
    raw["logging"]["directory"] = "logs/custom"
    save_config(config, raw)
    settings = load_settings(config)
    assert settings.database_path == PROJECT_ROOT / ".data/custom/custom.db"
    assert settings.logging.directory == PROJECT_ROOT / "logs/custom"


@pytest.mark.parametrize("change", ["unknown", "workers", "filename", "missing"])
def test_invalid_or_missing_configuration_fails(tmp_path: Path, change: str) -> None:
    config = write_config(tmp_path)
    raw = read_config(config)
    if change == "unknown":
        raw["typo"] = True
    elif change == "workers":
        raw["server"]["workers"] = 2
    elif change == "filename":
        raw["database_filename"] = "../other.db"
    else:
        del raw["data_dir"]
    save_config(config, raw)
    with pytest.raises(ValidationError):
        load_settings(config)


def test_missing_config_has_no_environment_fallback(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.toml")


def test_loguru_file_and_uvicorn_bridge_do_not_duplicate(settings) -> None:
    configure_logging(settings.logging)
    configure_logging(settings.logging)
    logger.bind(trace_id="trace-probe").info("loguru-probe")
    logging.getLogger("uvicorn.error").info("uvicorn-probe")
    logger.complete()
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert contents.count("loguru-probe") == 1
    assert contents.count("uvicorn-probe") == 1
    assert "trace-probe" in contents


def test_trace_id_is_written_to_loguru_file(settings) -> None:
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/hello")
    contents = (settings.logging.directory / settings.logging.filename).read_text()
    assert response_trace_id(response.headers) in contents
    assert "GET /api/v1/hello 200" in contents
