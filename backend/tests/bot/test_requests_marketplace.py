from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import Assignment, Message, RepairRequest
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_callback, message_created


async def _employee_submits_for_approval(harness: BotHarness, world: rf.BotWorld) -> None:
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(message_callback("m:find_provider", user_id=uid, chat_id=cid))
    location_payload = harness.payload_of("Кафе на Ленина")
    harness.reset()
    await harness.deliver(message_callback(location_payload, user_id=uid, chat_id=cid))
    equipment_payload = harness.payload_of("Полюс ВХС-1")
    harness.reset()
    await harness.deliver(message_callback(equipment_payload, user_id=uid, chat_id=cid))

    harness.reset()
    await harness.deliver(message_created("Течёт хладагент", user_id=uid, chat_id=cid))
    skip_payload = harness.payload_of(texts.BUTTON_NO_ERROR_CODE)
    harness.reset()
    await harness.deliver(message_callback(skip_payload, user_id=uid, chat_id=cid))
    urgent_payload = harness.payload_of(texts.URGENCY_URGENT)
    harness.reset()
    await harness.deliver(message_callback(urgent_payload, user_id=uid, chat_id=cid))

    for _ in range(2):
        cant_payload = harness.payload_of(texts.BUTTON_CANT_PHOTO)
        harness.reset()
        await harness.deliver(message_callback(cant_payload, user_id=uid, chat_id=cid))
        harness.reset()
        await harness.deliver(
            message_created("Оборудование труднодоступно", user_id=uid, chat_id=cid)
        )
    skip_photo_payload = harness.payload_of(texts.BUTTON_SKIP)
    harness.reset()
    await harness.deliver(message_callback(skip_photo_payload, user_id=uid, chat_id=cid))

    approval_payload = harness.payload_of(texts.APPROVAL_SEND)
    harness.reset()
    await harness.deliver(message_callback(approval_payload, user_id=uid, chat_id=cid))
    assert any("согласование" in t for t in harness.texts)


async def test_employee_sends_for_approval_manager_publishes(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await _employee_submits_for_approval(harness, world)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "approval_required"

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    harness.reset()
    await harness.deliver(
        message_callback("m:find_provider", user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("увидят исполнители" in t for t in harness.texts)
    publish_payload = harness.payload_of(texts.BUTTON_PUBLISH)

    harness.reset()
    await harness.deliver(
        message_callback(publish_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("опубликована" in t for t in harness.texts)

    await db_session.refresh(request)
    assert request.status == "searching"


async def test_employee_cannot_publish(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await _employee_submits_for_approval(harness, world)

    uid = int(world.employee_max_id)
    harness.reset()
    await harness.deliver(message_callback("m:find_provider", user_id=uid, chat_id=uid))
    titles = {b.text for b in harness.buttons()}
    assert texts.BUTTON_PUBLISH not in titles


async def test_provider_offer_then_manager_selects_then_provider_confirms(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await _employee_submits_for_approval(harness, world)

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    harness.reset()
    await harness.deliver(
        message_callback("m:find_provider", user_id=manager_uid, chat_id=manager_uid)
    )
    publish_payload = harness.payload_of(texts.BUTTON_PUBLISH)
    harness.reset()
    await harness.deliver(
        message_callback(publish_payload, user_id=manager_uid, chat_id=manager_uid)
    )

    dispatcher_uid = int(world.dispatcher_max_id)
    await harness.deliver(message_created("/start", user_id=dispatcher_uid, chat_id=dispatcher_uid))
    harness.reset()
    await harness.deliver(
        message_callback("m:available", user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    respond_payload = harness.payload_of(texts.BUTTON_RESPOND)

    harness.reset()
    await harness.deliver(
        message_callback(respond_payload, user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    today_payload = harness.payload_of("Завтра")
    harness.reset()
    await harness.deliver(
        message_callback(today_payload, user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    slot_payload = harness.payload_of(texts.OFFER_SLOT_DAY)
    harness.reset()
    await harness.deliver(
        message_callback(slot_payload, user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    later_payload = harness.payload_of(texts.OFFER_PRICE_LATER)
    harness.reset()
    await harness.deliver(
        message_callback(later_payload, user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    harness.reset()
    await harness.deliver(
        message_created(
            "Диагностика и мелкий ремонт", user_id=dispatcher_uid, chat_id=dispatcher_uid
        )
    )
    assert any("отправлено" in t for t in harness.texts)

    harness.reset()
    await harness.deliver(
        message_callback("m:my_requests", user_id=manager_uid, chat_id=manager_uid)
    )
    open_payload = harness.buttons()[0].payload
    harness.reset()
    await harness.deliver(message_callback(open_payload, user_id=manager_uid, chat_id=manager_uid))
    offers_payload = harness.payload_of("Предложения")

    harness.reset()
    await harness.deliver(
        message_callback(offers_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    select_payload = harness.payload_of(texts.BUTTON_SELECT_OFFER)
    harness.reset()
    await harness.deliver(
        message_callback(select_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    confirm_payload = harness.payload_of(texts.BUTTON_CONFIRM_OFFER)
    harness.reset()
    await harness.deliver(
        message_callback(confirm_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("выбран" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "awaiting_assignment_confirmation"

    harness.reset()
    await harness.deliver(
        message_callback("m:inbox", user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    accept_payload = harness.payload_of(texts.BUTTON_ACCEPT)
    harness.reset()
    await harness.deliver(
        message_callback(accept_payload, user_id=dispatcher_uid, chat_id=dispatcher_uid)
    )
    assert any("принята" in t for t in harness.texts)

    await db_session.refresh(request)
    assert request.status in {"accepted", "scheduled"}
    assignment = (await db_session.execute(select(Assignment))).scalars().one()
    assert assignment.state == "accepted"


async def _published(harness: BotHarness, db_session: AsyncSession) -> rf.BotWorld:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await _employee_submits_for_approval(harness, world)
    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    harness.reset()
    await harness.deliver(
        message_callback("m:find_provider", user_id=manager_uid, chat_id=manager_uid)
    )
    publish_payload = harness.payload_of(texts.BUTTON_PUBLISH)
    harness.reset()
    await harness.deliver(
        message_callback(publish_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    return world


async def test_marketplace_card_shows_public_fields(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _published(harness, db_session)
    uid = int(world.dispatcher_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=uid))
    harness.reset()
    await harness.deliver(message_callback("m:available", user_id=uid, chat_id=uid))

    card = harness.last_text
    assert texts.MARKETPLACE_EQUIPMENT.format(title="Полюс ВХС-1") in card
    assert "Район:" in card
    assert "Течёт хладагент" in card
    assert "Ленина" not in card
    titles = {b.text for b in harness.buttons()}
    assert {texts.BUTTON_RESPOND, texts.BUTTON_ASK_QUESTION} <= titles


async def test_provider_asks_question_before_offer(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _published(harness, db_session)
    uid = int(world.dispatcher_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=uid))
    harness.reset()
    await harness.deliver(message_callback("m:available", user_id=uid, chat_id=uid))
    question_payload = harness.payload_of(texts.BUTTON_ASK_QUESTION)
    harness.reset()
    await harness.deliver(message_callback(question_payload, user_id=uid, chat_id=uid))
    assert "Вопрос заказчику" in harness.last_text
    harness.reset()
    await harness.deliver(message_created("Какой хладагент?", user_id=uid, chat_id=uid))
    assert texts.MARKET_QUESTION_SENT in harness.texts

    message = (await db_session.execute(select(Message))).scalars().one()
    assert message.body == "Какой хладагент?"
    assert message.thread_provider_org_id == world.provider_org_id
    assert message.assignment_id is None
