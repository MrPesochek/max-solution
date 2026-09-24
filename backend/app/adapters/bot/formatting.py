from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.clock import utcnow

DAY_LABELS = {0: "Сегодня", 1: "Завтра"}


def zone(tz_name: str | None) -> tzinfo:
    if not tz_name:
        return UTC
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return UTC


def local_today(tz_name: str | None) -> datetime:
    """Начало текущих суток по месту — точка отсчёта для выбора дня выезда."""
    return utcnow().astimezone(zone(tz_name)).replace(hour=0, minute=0, second=0, microsecond=0)


def local_day_label(offset: int, tz_name: str | None) -> str:
    day = local_today(tz_name) + timedelta(days=offset)
    return DAY_LABELS.get(offset, day.strftime("%d.%m"))


def local_window_to_utc(
    day_offset: int, start_hour: int, end_hour: int, tz_name: str | None
) -> tuple[datetime, datetime]:
    """Слот «с HH до HH» в день `day_offset` по месту → пара UTC-меток для команды."""
    day = local_today(tz_name) + timedelta(days=day_offset)
    start = day.replace(hour=start_hour)
    end = day.replace(hour=end_hour)
    return start.astimezone(UTC), end.astimezone(UTC)


def tz_label(tz_name: str | None) -> str:
    return tz_name or "UTC"


def format_local_range(start: datetime, end: datetime, tz_name: str | None) -> str:
    """«09:00–13:00, 20.09 (Asia/Yekaterinburg)» — всегда по месту, пояс не скрыт."""
    tz = zone(tz_name)
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    label = tz_label(tz_name)
    if local_start.date() == local_end.date():
        return f"{local_start:%d.%m %H:%M}–{local_end:%H:%M} ({label})"
    return f"{local_start:%d.%m %H:%M}–{local_end:%d.%m %H:%M} ({label})"


def format_local_moment(value: datetime, tz_name: str | None) -> str:
    tz = zone(tz_name)
    local = value.astimezone(tz)
    return f"{local:%d.%m %H:%M} ({tz_label(tz_name)})"
