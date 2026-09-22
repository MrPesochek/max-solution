from collections.abc import Callable
from datetime import UTC, datetime

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def utcnow() -> datetime:
    return _now()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Подмена времени в тестах; None возвращает системные часы."""
    global _now
    _now = fn or (lambda: datetime.now(UTC))
