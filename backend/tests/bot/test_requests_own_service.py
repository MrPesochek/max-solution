from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import RepairRequest
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_callback, message_created


async def _drive_to_photos(harness: BotHarness, world: rf.BotWorld) -> None:
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(message_callback("m:my_service", user_id=uid, chat_id=cid))

    location_payload = harness.payload_of("Кафе на Ленина")
    harness.reset()
    await harness.deliver(message_callback(location_payload, user_id=uid, chat_id=cid))

    equipment_payload = harness.payload_of("Полюс ВХС-1")
    harness.reset()
    await harness.deliver(message_callback(equipment_payload, user_id=uid, chat_id=cid))
    assert "Кафе на Ленина" in harness.texts[0]
    assert "Холод-Сервис" in harness.texts[0]

    harness.reset()
    await harness.deliver(
        message_created("Компрессор гудит и не морозит", user_id=uid, chat_id=cid)
    )
    skip_payload = harness.payload_of(texts.BUTTON_NO_ERROR_CODE)
    harness.reset()
    await harness.deliver(message_callback(skip_payload, user_id=uid, chat_id=cid))
    normal_payload = harness.payload_of(texts.URGENCY_NORMAL)
    harness.reset()
    await harness.deliver(message_callback(normal_payload, user_id=uid, chat_id=cid))


async def test_full_flow_with_photos_and_submit(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _drive_to_photos(harness, world)
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)

    url1 = "https://max.test/photo-overview"
    harness.transport.download_results[url1] = rf.png_bytes()
    harness.reset()
    await harness.deliver(
        message_created("", user_id=uid, chat_id=cid, attachments=[rf.image_attachment(url1)])
    )
    assert any("сохранено" in t for t in harness.texts)

    url2 = "https://max.test/photo-nameplate"
    harness.transport.download_results[url2] = rf.png_bytes((1, 2, 3))
    harness.reset()
    await harness.deliver(
        message_created("", user_id=uid, chat_id=cid, attachments=[rf.image_attachment(url2)])
    )
    assert any("сохранено" in t for t in harness.texts)

    skip_photo_payload = harness.payload_of(texts.BUTTON_SKIP)
    harness.reset()
    await harness.deliver(message_callback(skip_photo_payload, user_id=uid, chat_id=cid))

    assert "Проверьте заявку" in harness.last_text
    assert "Фото: 2" in harness.last_text
    send_payload = harness.payload_of(texts.BUTTON_SEND)

    harness.reset()
    await harness.deliver(message_callback(send_payload, user_id=uid, chat_id=cid))
    assert any("отправлена" in t for t in harness.texts)

    requests = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert len(requests) == 1
    assert requests[0].status == "awaiting_provider"
    assert requests[0].photos_incomplete is False

    harness.reset()
    await harness.deliver(message_callback(send_payload, user_id=uid, chat_id=cid))
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    requests_after = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert len(requests_after) == 1


async def test_cannot_photo_marks_incomplete_but_allows_submit(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _drive_to_photos(harness, world)
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)

    cant_payload = harness.payload_of(texts.BUTTON_CANT_PHOTO)
    harness.reset()
    await harness.deliver(message_callback(cant_payload, user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(
        message_created("Точки доступа к оборудованию нет", user_id=uid, chat_id=cid)
    )
    assert any("не будет приложено" in t for t in harness.texts)

    cant_payload = harness.payload_of(texts.BUTTON_CANT_PHOTO)
    harness.reset()
    await harness.deliver(message_callback(cant_payload, user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(message_created("Нет доступа", user_id=uid, chat_id=cid))

    skip_photo_payload = harness.payload_of(texts.BUTTON_SKIP)
    harness.reset()
    await harness.deliver(message_callback(skip_photo_payload, user_id=uid, chat_id=cid))
    assert "Не все фото приложены" in harness.last_text

    send_payload = harness.payload_of(texts.BUTTON_SEND)
    harness.reset()
    await harness.deliver(message_callback(send_payload, user_id=uid, chat_id=cid))
    assert any("отправлена" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.photos_incomplete is True


async def test_no_confirmed_binding_offers_external_search(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(message_callback("m:my_service", user_id=uid, chat_id=cid))
    location_payload = harness.payload_of("Кафе на Ленина")
    harness.reset()
    await harness.deliver(message_callback(location_payload, user_id=uid, chat_id=cid))
    equipment_payload = harness.payload_of("Полюс ВХС-1")

    harness.reset()
    await harness.deliver(message_callback(equipment_payload, user_id=uid, chat_id=cid))

    assert any("Подтверждённой привязки" in t for t in harness.texts)
    requests = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert requests == []


async def test_interrupted_draft_resumes_same_request(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _drive_to_photos(harness, world)
    uid, cid = int(world.employee_max_id), int(world.employee_max_id)

    requests = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert len(requests) == 1
    first_id = requests[0].id

    harness.reset()
    await harness.deliver(message_created("/start", user_id=uid, chat_id=cid))
    harness.reset()
    await harness.deliver(message_callback("m:my_service", user_id=uid, chat_id=cid))
    assert "незавершённая заявка" in harness.last_text
    continue_payload = harness.payload_of(texts.RESUME_CONTINUE)

    harness.reset()
    await harness.deliver(message_callback(continue_payload, user_id=uid, chat_id=cid))
    assert texts.ASK_SYMPTOMS in harness.last_text

    requests_after = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert len(requests_after) == 1
    assert requests_after[0].id == first_id
