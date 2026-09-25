from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def rub_to_minor(value: str) -> int | None:
    """Пустая строка/пробелы — цена неизвестна (`None`), не ноль."""
    text = value.strip().replace(",", ".")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"некорректная сумма: {value!r}") from exc
    minor = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def minor_to_rub(amount_minor: int | None) -> str:
    if amount_minor is None:
        return ""
    rub = Decimal(amount_minor) / 100
    return f"{rub:.2f}"
