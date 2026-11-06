from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
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
