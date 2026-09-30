from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _date(value: Any) -> str:
    text = str(value or "")
    if not text or text.startswith("0001-01-01"):
        return "—"
    return f"{text[8:10]}.{text[5:7]}.{text[0:4]} {text[11:16]}".strip()


def _local_input(value: Any) -> str:
    text = str(value or "")
    if not text or text.startswith("0001-01-01"):
        return ""
    return text[:16]


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return str(value)
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


templates.env.filters["date1c"] = _date
templates.env.filters["local_input"] = _local_input
templates.env.filters["money"] = _money
