from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import set_clock
from app.infra.config import Settings
from tests import factories


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.integration_settings(
        monkeypatch,
        WORKER_HEARTBEAT_INTERVAL_MULTIPLIER="1",
        WORKER_HEARTBEAT_GRACE_SECONDS="5",
        WORKER_HEARTBEAT_WRITE_SECONDS="0",
    )


@dataclass
class Clock:
    now: datetime

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def clock() -> Iterator[Clock]:
    holder = Clock(datetime(2026, 9, 30, 12, 0, tzinfo=UTC))
    set_clock(lambda: holder.now)
    try:
        yield holder
    finally:
        set_clock(None)
