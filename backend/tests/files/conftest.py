from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.clock import set_clock
from app.infra.config import Settings, get_settings
from app.infra.storage.local import LocalFileStorage
from app.modules.files import api as files
from tests import factories
from tests.requests import factories as request_factories
from tests.requests.factories import World


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "files"


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> Iterator[Settings]:
    yield from factories.apply_test_settings(monkeypatch, FILE_STORAGE_PATH=str(storage_root))


@pytest.fixture(autouse=True)
def storage(settings: Settings, storage_root: Path) -> Iterator[LocalFileStorage]:
    store = LocalFileStorage(storage_root)
    files.set_storage(store)
    yield store
    files.set_storage(None)


@pytest.fixture
def override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:

    def apply(**env: str) -> Settings:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    return apply


@pytest.fixture(autouse=True)
def _clock() -> Iterator[None]:
    yield
    set_clock(None)


@pytest_asyncio.fixture
async def world(clean_db: None) -> AsyncIterator[World]:
    yield await request_factories.build_world()


@pytest_asyncio.fixture
async def other_world(clean_db: None) -> AsyncIterator[World]:
    yield await request_factories.build_foreign_world()
