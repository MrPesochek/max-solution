from collections.abc import Iterator
from dataclasses import dataclass
from itertools import count
from typing import Any

import pytest
from maxapi import Bot, Dispatcher
from maxapi.methods.types.getted_updates import process_update_webhook

from app.adapters.bot import runtime as bot_runtime
from app.adapters.bot import updates
from app.adapters.bot.handlers import build_router
from app.adapters.bot.runtime import BotRuntime
from app.infra.config import Settings
from app.infra.max.transport import FakeMaxTransport
from tests.factories import apply_test_settings

BOT_TOKEN = "123456:test-bot-token"
WEBHOOK_SECRET = "webhook-secret-1234"
CHAT_ID = 500
USER_ID = 77


@pytest.fixture
def bot_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from apply_test_settings(
        monkeypatch,
        MAX_UPDATES_MODE="webhook",
        MAX_WEBHOOK_SECRET=WEBHOOK_SECRET,
        PUBLIC_BASE_URL="https://example.test",
    )


@dataclass
class BotHarness:
    runtime: BotRuntime
    transport: FakeMaxTransport

    async def deliver(self, event_json: dict[str, Any]) -> updates.Outcome:
        event = await process_update_webhook(event_json=event_json, bot=self.runtime.bot)
        assert event is not None, "событие не распознано библиотекой"
        return await updates.process(self.runtime.dispatcher, event)

    @property
    def texts(self) -> list[str]:
        return [call.text or "" for call in self.transport.sent_messages]

    @property
    def last_text(self) -> str:
        assert self.transport.sent_messages, "бот ничего не отправил"
        return self.transport.sent_messages[-1].text or ""

    def buttons(self, index: int = -1) -> list[Any]:
        call = self.transport.sent_messages[index]
        found: list[Any] = []
        for attachment in call.attachments or []:
            payload = getattr(attachment, "payload", None)
            for row in getattr(payload, "buttons", []) or []:
                found.extend(row)
        return found

    def payload_of(self, text: str, index: int = -1) -> str:
        for button in self.buttons(index):
            if button.text == text:
                return str(button.payload)
        raise AssertionError(f"кнопка {text!r} не найдена")

    def payload_starting(self, prefix: str, index: int = -1) -> str:
        for button in self.buttons(index):
            if str(button.text).startswith(prefix):
                return str(button.payload)
        raise AssertionError(f"кнопка «{prefix}…» не найдена")

    def find_payload(self, text: str) -> str:
        for index in range(len(self.transport.sent_messages) - 1, -1, -1):
            for button in self.buttons(index):
                if str(button.text).startswith(text):
                    return str(button.payload)
        raise AssertionError(f"кнопка «{text}» не найдена ни в одном сообщении")

    def reset(self) -> None:
        self.transport.sent_messages.clear()
        self.transport.answered_callbacks.clear()


def build_harness(transport: FakeMaxTransport | None = None) -> BotHarness:
    sender = transport or FakeMaxTransport()
    bot = Bot(token=BOT_TOKEN, auto_requests=False)
    dispatcher = Dispatcher(router_id="test")
    dispatcher.include_routers(build_router(sender))
    dispatcher.errors()(updates.capture_error)
    runtime = BotRuntime(
        bot=bot,
        dispatcher=dispatcher,
        transport=sender,
        mode="webhook",
        webhook_url="https://example.test/max/webhook",
        secret=WEBHOOK_SECRET,
    )
    return BotHarness(runtime=runtime, transport=sender)


@pytest.fixture
def harness(bot_settings: Settings, clean_db: None) -> Iterator[BotHarness]:
    built = build_harness()
    bot_runtime.set_runtime(built.runtime)
    try:
        yield built
    finally:
        bot_runtime.set_runtime(None)


_mids = count(1)
_callbacks = count(1)


def max_user(user_id: int = USER_ID, name: str = "Иван") -> dict[str, Any]:
    return {
        "user_id": user_id,
        "first_name": name,
        "is_bot": False,
        "last_activity_time": 1,
    }


def message_created(
    text: str,
    *,
    user_id: int = USER_ID,
    chat_id: int = CHAT_ID,
    mid: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 1_700_000_000_000,
        "message": {
            "sender": max_user(user_id),
            "recipient": {"chat_id": chat_id, "chat_type": "dialog"},
            "timestamp": 1_700_000_000_000,
            "body": {
                "mid": mid or f"mid-{next(_mids)}",
                "seq": 1,
                "text": text,
                "attachments": attachments or [],
            },
        },
    }


def contact_message(
    phone: str, *, user_id: int = USER_ID, chat_id: int = CHAT_ID
) -> dict[str, Any]:
    vcf = f"BEGIN:VCARD\nVERSION:3.0\nFN:Иван\nTEL:{phone}\nEND:VCARD"
    return message_created(
        "",
        user_id=user_id,
        chat_id=chat_id,
        attachments=[{"type": "contact", "payload": {"vcf_info": vcf}}],
    )


def message_callback(
    payload: str,
    *,
    user_id: int = USER_ID,
    chat_id: int = CHAT_ID,
    callback_id: str | None = None,
) -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "timestamp": 1_700_000_000_000,
        "callback": {
            "timestamp": 1_700_000_000_000,
            "callback_id": callback_id or f"cb-{next(_callbacks)}",
            "payload": payload,
            "user": max_user(user_id),
        },
        "message": {
            "sender": max_user(user_id),
            "recipient": {"chat_id": chat_id, "chat_type": "dialog"},
            "timestamp": 1_700_000_000_000,
            "body": {"mid": f"mid-{next(_mids)}", "seq": 1, "text": "меню"},
        },
    }


def bot_started(
    *, payload: str | None = None, user_id: int = USER_ID, chat_id: int = CHAT_ID
) -> dict[str, Any]:
    return {
        "update_type": "bot_started",
        "timestamp": 1_700_000_000_000,
        "chat_id": chat_id,
        "user": max_user(user_id),
        "payload": payload,
    }


def bot_stopped(*, user_id: int = USER_ID, chat_id: int = CHAT_ID) -> dict[str, Any]:
    return {
        "update_type": "bot_stopped",
        "timestamp": 1_700_000_000_001,
        "chat_id": chat_id,
        "user": max_user(user_id),
    }
