from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from app.adapters.bot.handlers import visit_terms
from app.core.clock import set_clock

TZ = "Asia/Yekaterinburg"


@pytest.fixture
def evening() -> Iterator[None]:
    set_clock(lambda: datetime(2026, 6, 15, 13, 0, tzinfo=UTC))
    yield
    set_clock(None)


def test_today_offers_only_unfinished_slots(evening: None) -> None:
    assert visit_terms.open_slots(0, TZ) == ["evening"]
    assert visit_terms.open_slots(1, TZ) == ["morning", "day", "evening"]
    assert visit_terms.open_day_offsets(TZ) == [0, 1, 2]


def test_today_hidden_after_last_slot() -> None:
    set_clock(lambda: datetime(2026, 6, 15, 17, 0, tzinfo=UTC))
    try:
        assert visit_terms.open_slots(0, TZ) == []
        assert visit_terms.open_day_offsets(TZ) == [1, 2]
    finally:
        set_clock(None)
