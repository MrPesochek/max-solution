from __future__ import annotations

from dataclasses import dataclass

from app.adapters.bot import texts
from app.infra.max.types import (
    OPEN_APP_PAYLOAD_PREFIX,
    Button,
    ButtonCallback,
    ButtonRequestContact,
    OutgoingAttachment,
    keyboard,
    webapp_button,
)

PAYLOAD_LIMIT = 128

ACTION = "a"
MENU = "m"
DIALOG = "d"
SELECT_ORG = "s"
OPEN_APP = OPEN_APP_PAYLOAD_PREFIX.rstrip(":")


@dataclass(frozen=True, slots=True)
class Payload:
    kind: str
    value: str

    @property
    def parts(self) -> list[str]:
        return self.value.split(":")


def parse_payload(raw: str | None) -> Payload | None:
    if not raw:
        return None
    kind, sep, value = raw.partition(":")
    if not sep or kind not in (ACTION, MENU, DIALOG, SELECT_ORG, OPEN_APP):
        return None
    return Payload(kind=kind, value=value)


def _payload(kind: str, *parts: str) -> str:
    raw = ":".join((kind, *parts))
    if len(raw) > PAYLOAD_LIMIT:
        raise ValueError("payload кнопки длиннее допустимого")
    return raw


def action_button(text: str, code: str) -> Button:
    return ButtonCallback(text=text, payload=_payload(ACTION, code))


def menu_button(text: str, key: str) -> Button:
    return ButtonCallback(text=text, payload=_payload(MENU, key))


def dialog_button(text: str, step: str, value: str) -> Button:
    return ButtonCallback(text=text, payload=_payload(DIALOG, step, value))


def select_org_button(text: str, membership_public_id: str) -> Button:
    return ButtonCallback(text=text, payload=_payload(SELECT_ORG, membership_public_id))


def contact_button(text: str = texts.SHARE_CONTACT) -> Button:
    return ButtonRequestContact(text=text)


def open_app(text: str, screen: str, object_public_id: str | None = None) -> Button:
    return webapp_button(text, screen, object_public_id)


def rows(*button_rows: list[Button]) -> OutgoingAttachment:
    return keyboard([row for row in button_rows if row])


def paginate[T](items: list[T], page: int, size: int) -> tuple[list[T], bool, bool]:
    """Срез страницы и признаки наличия соседних страниц."""
    start = max(page, 0) * size
    chunk = items[start : start + size]
    return chunk, start > 0, start + size < len(items)


def nav_row(step: str, page: int, *, has_prev: bool, has_next: bool) -> list[Button]:
    row: list[Button] = []
    if has_prev:
        row.append(dialog_button(texts.BUTTON_PREV, step, f"page={page - 1}"))
    if has_next:
        row.append(dialog_button(texts.BUTTON_MORE, step, f"page={page + 1}"))
    return row


def back_cancel_row(step: str, *, with_back: bool = True) -> list[Button]:
    row: list[Button] = []
    if with_back:
        row.append(dialog_button(texts.BUTTON_BACK, step, "back"))
    row.append(dialog_button(texts.BUTTON_CANCEL, step, "cancel"))
    return row
