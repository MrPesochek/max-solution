from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.clock import set_clock
from tests.requests import factories
from tests.requests.factories import World


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
