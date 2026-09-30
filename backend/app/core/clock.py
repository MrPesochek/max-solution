from collections.abc import Callable
from datetime import UTC, datetime

_now: Callable[[], datetime] = lambda: datetime.now(UTC)


def utcnow() -> datetime:
    return _now()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    global _now
    _now = fn or (lambda: datetime.now(UTC))
