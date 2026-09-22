from dataclasses import dataclass

from app.core.errors import ValidationFailed
from app.infra.config import get_settings


@dataclass(frozen=True, slots=True)
class Price:
    """amount_minor=None — цена неизвестна; 0 — явно бесплатно и требует основания."""

    amount_minor: int | None
    currency: str | None
    zero_cost_reason: str | None = None
    vat_mode: str | None = None

    @property
    def is_known(self) -> bool:
        return self.amount_minor is not None


def validate_price(price: Price) -> Price:
    if price.amount_minor is None:
        return Price(None, None, None, price.vat_mode)
    if price.amount_minor < 0:
        raise ValidationFailed("Сумма не может быть отрицательной", field="amount_minor")
    currency = price.currency or get_settings().supported_currency
    if currency != get_settings().supported_currency:
        raise ValidationFailed("Валюта не поддерживается", field="currency")
    if price.amount_minor == 0 and not (price.zero_cost_reason or "").strip():
        raise ValidationFailed("Для нулевой стоимости укажите основание", field="zero_cost_reason")
    return Price(price.amount_minor, currency, price.zero_cost_reason, price.vat_mode)


THOUSANDS_SEPARATOR = " "
CURRENCY_SIGNS = {"RUB": "₽"}
PRICE_PENDING = "стоимость уточняется"


def format_money(amount_minor: int, currency: str | None = None) -> str:
    """«1 500 ₽», «1 500,50 ₽»: копейки только если они есть, без float."""
    sign = "-" if amount_minor < 0 else ""
    whole, fraction = divmod(abs(amount_minor), 100)
    rubles = f"{whole:,}".replace(",", THOUSANDS_SEPARATOR)
    text = f"{sign}{rubles},{fraction:02d}" if fraction else f"{sign}{rubles}"
    code = currency or get_settings().supported_currency
    return f"{text}{THOUSANDS_SEPARATOR}{CURRENCY_SIGNS.get(code, code)}"


def format_price(
    amount_minor: int | None, currency: str | None = None, zero_cost_reason: str | None = None
) -> str:
    """Цена для текста: неизвестная не выдаётся за ноль, ноль всегда с основанием."""
    if amount_minor is None:
        return PRICE_PENDING
    money = format_money(amount_minor, currency)
    if amount_minor == 0:
        return f"{money} (основание: {(zero_cost_reason or '').strip() or '—'})"
    return money
