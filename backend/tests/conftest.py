from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import upgrade_database
from app.main import create_app
from tests.helpers import settings_for


@pytest.fixture
def anyio_backend() -> str:
    # SQLAlchemy's aiosqlite driver uses asyncio; this is a test backend contract.
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
