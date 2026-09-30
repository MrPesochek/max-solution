from collections.abc import Iterator
from pathlib import Path

import pytest

from app.infra.config import Settings
from app.modules.files import api as files
from tests import factories

CONNECTOR_API_KEY = "rk_demo_" + "a" * 12 + "_" + "b" * 32


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Settings]:
    monkeypatch.setenv("CONNECTOR_API_KEY", CONNECTOR_API_KEY)
    files.set_storage(None)
    yield from factories.apply_test_settings(
        monkeypatch, APP_ENV="demo", FILE_STORAGE_PATH=str(tmp_path / "files")
    )
