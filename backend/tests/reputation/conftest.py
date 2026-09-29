from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.clock import set_clock
from app.infra.config import Settings
from tests import factories as base_factories
from tests.requests import factories
from tests.requests.factories import World


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from base_factories.apply_test_settings(monkeypatch)


@dataclass(slots=True)
class Clock:
    now: datetime

    def advance(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


@pytest.fixture
def clock() -> Iterator[Clock]:
    holder = Clock(datetime.now(UTC))
    set_clock(lambda: holder.now)
    yield holder
    set_clock(None)


@pytest_asyncio.fixture
async def world(clean_db: None) -> AsyncIterator[World]:
    yield await factories.build_world()


@pytest_asyncio.fixture
async def other_world(clean_db: None) -> AsyncIterator[World]:
    yield await factories.build_foreign_world()
