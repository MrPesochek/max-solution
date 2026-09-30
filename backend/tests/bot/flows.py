from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import RepairRequest, User
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_callback, message_created


async def press(harness: BotHarness, payload: str, uid: int) -> None:
    harness.reset()
    await harness.deliver(message_callback(payload, user_id=uid, chat_id=uid))


async def say(harness: BotHarness, text: str, uid: int) -> None:
    harness.reset()
    await harness.deliver(message_created(text, user_id=uid, chat_id=uid))


async def open_menu(harness: BotHarness, key: str, uid: int) -> None:
    await press(harness, f"m:{key}", uid)


async def collect_request(harness: BotHarness, uid: int, *, menu_key: str) -> None:
    await say(harness, "/start", uid)
    await open_menu(harness, menu_key, uid)
    await press(harness, harness.payload_of("Кафе на Ленина"), uid)
    await press(harness, harness.payload_of("Полюс ВХС-1"), uid)
    await say(harness, "Не морозит", uid)
    await press(harness, harness.payload_of(texts.BUTTON_NO_ERROR_CODE), uid)
    await press(harness, harness.payload_of(texts.URGENCY_NORMAL), uid)
    for _ in range(2):
        await press(harness, harness.payload_of(texts.BUTTON_CANT_PHOTO), uid)
        await say(harness, "Нет доступа", uid)
    await press(harness, harness.payload_of(texts.BUTTON_SKIP), uid)


async def submit_own_service(harness: BotHarness, world: rf.BotWorld) -> None:
    uid = int(world.employee_max_id)
    await collect_request(harness, uid, menu_key="my_service")
    await press(harness, harness.payload_of(texts.BUTTON_SEND), uid)


async def submit_for_approval(harness: BotHarness, world: rf.BotWorld) -> None:
    uid = int(world.employee_max_id)
    await collect_request(harness, uid, menu_key="find_provider")
    await press(harness, harness.payload_of(texts.APPROVAL_SEND), uid)


async def accept_by_dispatcher(harness: BotHarness, world: rf.BotWorld) -> None:
    did = int(world.dispatcher_max_id)
    await say(harness, "/start", did)
    await open_menu(harness, "inbox", did)
    await press(harness, harness.payload_of(texts.BUTTON_ACCEPT), did)


async def propose_visit(harness: BotHarness, world: rf.BotWorld, *, amount: str) -> None:
    did = int(world.dispatcher_max_id)
    await open_menu(harness, "in_progress", did)
    await press(harness, harness.payload_of(texts.BUTTON_PROPOSE_VISIT), did)
    await press(harness, harness.payload_of("Завтра"), did)
    await press(harness, harness.payload_of(texts.OFFER_SLOT_DAY), did)
    await press(harness, harness.payload_of(texts.OFFER_PRICE_SUM), did)
    await say(harness, amount, did)
    await say(harness, "Диагностика компрессора", did)


async def open_first_card(harness: BotHarness, uid: int) -> None:
    await say(harness, "/start", uid)
    await open_menu(harness, "my_requests", uid)
    await press(harness, str(harness.buttons()[0].payload), uid)


async def only_request(db_session: AsyncSession) -> RepairRequest:
    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    await db_session.refresh(request)
    return request


async def user_id_of(db_session: AsyncSession, max_user_id: str) -> uuid.UUID:
    return (
        await db_session.execute(select(User.id).where(User.max_user_id == max_user_id))
    ).scalar_one()
