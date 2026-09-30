from __future__ import annotations

from typing import Any

from maxapi.enums.attachment import AttachmentType
from maxapi.enums.parse_mode import TextFormat
from maxapi.types.attachments.attachment import Attachment, ButtonsPayload
from maxapi.types.attachments.buttons import CallbackButton as ButtonCallback
from maxapi.types.attachments.buttons import InlineButtonUnion as Button
from maxapi.types.attachments.buttons import LinkButton as ButtonLink
from maxapi.types.attachments.buttons import OpenAppButton
from maxapi.types.attachments.buttons import RequestContactButton as ButtonRequestContact
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageForCallback as NewMessageBody

from app.infra.config import get_settings
from app.infra.max.deeplinks import webapp_target

__all__ = [
    "Attachment",
    "AttachmentButton",
    "Button",
    "ButtonCallback",
    "ButtonLink",
    "ButtonOpenApp",
    "ButtonRequestContact",
    "NewMessageBody",
    "OutgoingAttachment",
    "TextFormat",
    "keyboard",
    "open_app_callback",
    "open_webapp_button",
    "webapp_button",
]

OutgoingAttachment = Attachment

OPEN_BUTTON_TEXT = "Открыть"
OPEN_APP_PAYLOAD_PREFIX = "o:"


class ButtonOpenApp(OpenAppButton):
    def __init__(self, **data: Any) -> None:
        url = data.pop("url", None)
        if url is not None and data.get("web_app") is None:
            data["web_app"] = url
        super().__init__(**data)


def keyboard(rows: list[list[Button]]) -> AttachmentButton:
    return AttachmentButton(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=ButtonsPayload(buttons=rows),
        bot=None,
    )


def webapp_start_payload(screen: str, object_public_id: str | None = None) -> str | None:
    return webapp_target(screen, object_public_id)


def open_app_callback(text: str, target: str | None) -> Button:
    return ButtonCallback(text=text, payload=OPEN_APP_PAYLOAD_PREFIX + (target or ""))


def webapp_button(text: str, screen: str, object_public_id: str | None = None) -> Button:
    settings = get_settings()
    if settings.max_webapp_mode == "link":
        return open_app_callback(text, webapp_target(screen, object_public_id))
    if settings.max_bot_username:
        return ButtonOpenApp(
            text=text,
            web_app=settings.max_bot_username,
            payload=webapp_start_payload(screen, object_public_id),
        )
    base = settings.public_base_url.rstrip("/")
    query = "&".join(
        f"{key}={value}"
        for key, value in (("screen", screen), ("id", object_public_id))
        if value is not None
    )
    return ButtonLink(text=text, url=f"{base}/?{query}" if query else base)


def open_webapp_button(screen: str, object_public_id: str | None = None) -> OutgoingAttachment:
    return keyboard([[webapp_button(OPEN_BUTTON_TEXT, screen, object_public_id)]])
