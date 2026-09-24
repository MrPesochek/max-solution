from __future__ import annotations

from datetime import datetime

from app.adapters.bot import formatting, texts
from app.core.money import format_price


def price_text(
    amount_minor: int | None,
    currency: str | None = None,
    zero_cost_reason: str | None = None,
    vat_mode: str | None = None,
) -> str:
    text = format_price(amount_minor, currency, zero_cost_reason)
    vat = texts.VAT_LABELS.get(vat_mode or "") if amount_minor else None
    return f"{text}, {vat}" if vat else text


def window_text(start: datetime | None, end: datetime | None, tz: str | None) -> str:
    if start is None or end is None:
        return texts.REQUEST_CARD_VISIT_UNKNOWN
    return formatting.format_local_range(start, end, tz)


def visit_lines(
    *,
    number: int | str,
    version: int,
    window_start: datetime | None,
    window_end: datetime | None,
    amount_minor: int | None,
    currency: str | None,
    zero_cost_reason: str | None,
    vat_mode: str | None,
    scope: str | None,
    valid_until: datetime,
    tz: str | None,
) -> list[str]:
    return [
        texts.VISIT_PROPOSAL_TITLE.format(number=number, version=version),
        texts.VISIT_PROPOSAL_WINDOW.format(window=window_text(window_start, window_end, tz)),
        texts.VISIT_PROPOSAL_PRICE.format(
            price=price_text(amount_minor, currency, zero_cost_reason, vat_mode)
        ),
        texts.VISIT_PROPOSAL_SCOPE.format(scope=scope or "—"),
        texts.VISIT_PROPOSAL_VALID.format(
            valid_until=formatting.format_local_moment(valid_until, tz)
        ),
    ]


def quote_lines(
    *,
    number: int | str,
    version: int,
    description: str | None,
    amount_minor: int | None,
    currency: str | None,
    zero_cost_reason: str | None,
    vat_mode: str | None,
    valid_until: datetime,
    tz: str | None,
) -> list[str]:
    return [
        texts.REPAIR_QUOTE_TITLE.format(number=number, version=version),
        texts.REPAIR_QUOTE_SCOPE.format(scope=description or "—"),
        texts.REPAIR_QUOTE_PRICE.format(
            price=price_text(amount_minor, currency, zero_cost_reason, vat_mode)
        ),
        texts.REPAIR_QUOTE_VALID.format(
            valid_until=formatting.format_local_moment(valid_until, tz)
        ),
    ]


def offer_lines(
    *,
    provider_name: str | None,
    version: int,
    window_start: datetime | None,
    window_end: datetime | None,
    amount_minor: int | None,
    currency: str | None,
    zero_cost_reason: str | None,
    vat_mode: str | None,
    scope: str | None,
    valid_until: datetime,
    tz: str | None,
) -> list[str]:
    return [
        texts.OFFER_TITLE.format(
            name=provider_name or texts.OFFER_PROVIDER_UNKNOWN, version=version
        ),
        texts.VISIT_PROPOSAL_WINDOW.format(window=window_text(window_start, window_end, tz)),
        texts.VISIT_PROPOSAL_PRICE.format(
            price=price_text(amount_minor, currency, zero_cost_reason, vat_mode)
        ),
        texts.VISIT_PROPOSAL_SCOPE.format(scope=scope or "—"),
        texts.VISIT_PROPOSAL_VALID.format(
            valid_until=formatting.format_local_moment(valid_until, tz)
        ),
    ]
