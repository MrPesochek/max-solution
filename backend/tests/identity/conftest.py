from collections.abc import Iterator

import pytest

from app.infra.config import Settings
from tests import factories


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(monkeypatch)
