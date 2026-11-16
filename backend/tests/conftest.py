from collections.abc import Iterator
from pathlib import Path
from shutil import copytree, ignore_patterns

import pytest
from fastapi.testclient import TestClient

from app import config
from app.application import create_app
from app.config import BACKEND_ROOT, Settings
from entrypoints import service, service_control
from migrations.operations import upgrade_database
from tests.helpers import settings_for


@pytest.fixture
def anyio_backend() -> str:
    # SQLAlchemy 的 aiosqlite 驱动使用 asyncio；这是测试后端的固定约定。
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = settings_for(tmp_path)
    upgrade_database(settings)
    return settings


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def service_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在独立项目中运行真实入口，固定 .run 不得落入日常项目。"""
    project = tmp_path / "project with spaces 中文"
    backend = project / "backend"
    copytree(
        BACKEND_ROOT,
        backend,
        ignore=ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "tests",
            ".env*",
            ".secrets*",
        ),
    )
    (backend / ".venv").symlink_to(BACKEND_ROOT / ".venv", target_is_directory=True)
    (project / "configs").mkdir()
    (project / "configs/app.toml").write_bytes(config.CONFIG_FILE.read_bytes())
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.setattr(service_control, "PROJECT_ROOT", project)
    monkeypatch.setattr(service, "BACKEND_ROOT", backend)
    monkeypatch.setattr(service, "CONFIG_FILE", project / "configs/app.toml")
    return project
