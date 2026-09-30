from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.core import ids
from app.core.actor import UserActor
from app.core.clock import utcnow
from app.db.models import Assignment, Membership, Message, RepairRequest, User
from app.modules.requests import api
from app.worker import notification_templates as templates
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_callback, message_created


async def _submit_and_accept(harness: BotHarness, world: rf.BotWorld) -> None:
    uid = int(world.employee_max_id)
    await harness.deliver(message_created("/start", user_id=uid, chat_id=uid))
    harness.reset()
    await harness.deliver(message_callback("m:my_service", user_id=uid, chat_id=uid))
    location_payload = harness.payload_of("Кафе на Ленина")
    harness.reset()
    await harness.deliver(message_callback(location_payload, user_id=uid, chat_id=uid))
    equipment_payload = harness.payload_of("Полюс ВХС-1")
    harness.reset()
    await harness.deliver(message_callback(equipment_payload, user_id=uid, chat_id=uid))
    harness.reset()
    await harness.deliver(message_created("Не включается", user_id=uid, chat_id=uid))
    skip_payload = harness.payload_of(texts.BUTTON_NO_ERROR_CODE)
    harness.reset()
    await harness.deliver(message_callback(skip_payload, user_id=uid, chat_id=uid))
    normal_payload = harness.payload_of(texts.URGENCY_NORMAL)
    harness.reset()
    await harness.deliver(message_callback(normal_payload, user_id=uid, chat_id=uid))
    for _ in range(2):
        cant_payload = harness.payload_of(texts.BUTTON_CANT_PHOTO)
        harness.reset()
        await harness.deliver(message_callback(cant_payload, user_id=uid, chat_id=uid))
        harness.reset()
        await harness.deliver(message_created("Нет доступа", user_id=uid, chat_id=uid))
    skip_photo_payload = harness.payload_of(texts.BUTTON_SKIP)
    harness.reset()
    await harness.deliver(message_callback(skip_photo_payload, user_id=uid, chat_id=uid))
    send_payload = harness.payload_of(texts.BUTTON_SEND)
    harness.reset()
    await harness.deliver(message_callback(send_payload, user_id=uid, chat_id=uid))


async def test_customer_replies_to_provider_message_via_notification_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_and_accept(harness, world)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assignment = (await db_session.execute(select(Assignment))).scalars().one()
    dispatcher_membership = (
        (
            await db_session.execute(
                select(Membership).where(Membership.organization_id == world.provider_org_id)
            )
        )
        .scalars()
        .one()
    )
    dispatcher = UserActor(
        user_id=dispatcher_membership.user_id,
        membership_id=dispatcher_membership.id,
        organization_id=world.provider_org_id,
        role="provider_dispatcher",
    )

    await api.accept_assignment(
        dispatcher, request.id, assignment_id=assignment.id, expected_version=request.version
    )
    await db_session.refresh(request)

    await api.post_message(
        dispatcher,
        request.id,
        body="Уточните, пожалуйста, модель компрессора",
        assignment_id=assignment.id,
        expected_version=request.version,
    )

    manager = (
        await db_session.execute(select(User).where(User.max_user_id == world.manager_max_id))
    ).scalar_one()

    payload = {"request_id": ids.encode("request", request.id)}
    message = await templates.render(
        db_session, "message.created", payload, recipient_user_id=manager.id, now=utcnow()
    )
    await db_session.commit()
    reply_payload = message.attachments[0].payload.buttons[0][0].payload

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    harness.reset()
    await harness.deliver(message_callback(reply_payload, user_id=manager_uid, chat_id=manager_uid))
    assert "заявке" in harness.last_text

    harness.reset()
    await harness.deliver(
        message_created(
            "Компрессор Danfoss, модель на шильдике не видна",
            user_id=manager_uid,
            chat_id=manager_uid,
        )
    )
    assert any("Ответ отправлен" in t for t in harness.texts)

    messages = (await db_session.execute(select(Message).order_by(Message.id))).scalars().all()
    bodies = [m.body for m in messages]
    assert any("Danfoss" in b for b in bodies)
    assert all(m.request_id == request.id for m in messages)
