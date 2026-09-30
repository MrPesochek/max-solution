from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.core.clock import set_clock
from app.db.models import BotAction, CancellationRequest, RepairRequest, VisitProposal
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_callback, message_created

APPROVE_VISIT = "Согласовать выезд"


async def _submit_own_service_request(harness: BotHarness, world: rf.BotWorld) -> None:
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
    await harness.deliver(message_created("Не морозит", user_id=uid, chat_id=uid))
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


async def _accept_by_dispatcher(harness: BotHarness, world: rf.BotWorld) -> None:
    did = int(world.dispatcher_max_id)
    await harness.deliver(message_created("/start", user_id=did, chat_id=did))
    harness.reset()
    await harness.deliver(message_callback("m:inbox", user_id=did, chat_id=did))
    accept_payload = harness.payload_of(texts.BUTTON_ACCEPT)
    harness.reset()
    await harness.deliver(message_callback(accept_payload, user_id=did, chat_id=did))


async def _propose_visit(harness: BotHarness, world: rf.BotWorld, *, amount: str) -> None:
    did = int(world.dispatcher_max_id)
    harness.reset()
    await harness.deliver(message_callback("m:in_progress", user_id=did, chat_id=did))
    propose_payload = harness.payload_of(texts.BUTTON_PROPOSE_VISIT)
    harness.reset()
    await harness.deliver(message_callback(propose_payload, user_id=did, chat_id=did))
    today_payload = harness.payload_of("Завтра")
    harness.reset()
    await harness.deliver(message_callback(today_payload, user_id=did, chat_id=did))
    slot_payload = harness.payload_of(texts.OFFER_SLOT_DAY)
    harness.reset()
    await harness.deliver(message_callback(slot_payload, user_id=did, chat_id=did))
    sum_payload = harness.payload_of(texts.OFFER_PRICE_SUM)
    harness.reset()
    await harness.deliver(message_callback(sum_payload, user_id=did, chat_id=did))
    harness.reset()
    await harness.deliver(message_created(amount, user_id=did, chat_id=did))
    harness.reset()
    await harness.deliver(message_created("Диагностика компрессора", user_id=did, chat_id=did))


async def _open_card_and_get_button(
    harness: BotHarness, world: rf.BotWorld, *, button_text: str
) -> str:
    uid = int(world.manager_max_id)
    harness.reset()
    await harness.deliver(message_callback("m:my_requests", user_id=uid, chat_id=uid))
    open_payload = harness.buttons()[0].payload
    harness.reset()
    await harness.deliver(message_callback(open_payload, user_id=uid, chat_id=uid))
    return harness.payload_starting(button_text)


async def test_manager_approves_visit_and_a13_stale_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)
    await _propose_visit(harness, world, amount="1500")

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    stale_approve = await _open_card_and_get_button(harness, world, button_text=APPROVE_VISIT)

    await _propose_visit(harness, world, amount="2000")

    harness.reset()
    await harness.deliver(message_callback(stale_approve, user_id=manager_uid, chat_id=manager_uid))
    assert any("изменились" in t or "истёк" in t or "версии" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status != "scheduled"

    fresh_approve = await _open_card_and_get_button(harness, world, button_text=APPROVE_VISIT)
    harness.reset()
    await harness.deliver(message_callback(fresh_approve, user_id=manager_uid, chat_id=manager_uid))
    assert any("Выезд согласован" in t for t in harness.texts)

    await db_session.refresh(request)
    assert request.status == "scheduled"


async def test_employee_does_not_see_approval_buttons(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)
    await _propose_visit(harness, world, amount="1500")

    employee_uid = int(world.employee_max_id)
    harness.reset()
    await harness.deliver(
        message_callback("m:my_requests", user_id=employee_uid, chat_id=employee_uid)
    )
    open_payload = harness.buttons()[0].payload
    harness.reset()
    await harness.deliver(
        message_callback(open_payload, user_id=employee_uid, chat_id=employee_uid)
    )
    titles = {b.text for b in harness.buttons()}
    assert not any(t.startswith(APPROVE_VISIT) for t in titles)


async def test_completion_confirm_and_problem(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)
    await _propose_visit(harness, world, amount="1500")

    manager_uid = int(world.manager_max_id)
    approve_payload = await _open_card_and_get_button(harness, world, button_text=APPROVE_VISIT)
    harness.reset()
    await harness.deliver(
        message_callback(approve_payload, user_id=manager_uid, chat_id=manager_uid)
    )

    did = int(world.dispatcher_max_id)
    harness.reset()
    await harness.deliver(message_callback("m:in_progress", user_id=did, chat_id=did))
    start_payload = harness.payload_of(texts.BUTTON_START_WORK)
    harness.reset()
    await harness.deliver(message_callback(start_payload, user_id=did, chat_id=did))

    harness.reset()
    await harness.deliver(message_callback("m:in_progress", user_id=did, chat_id=did))
    report_payload = harness.payload_of(texts.BUTTON_REPORT_DONE)
    harness.reset()
    await harness.deliver(message_callback(report_payload, user_id=did, chat_id=did))
    not_resolved_payload = harness.payload_of(texts.OUTCOME_BUTTON_NOT_RESOLVED)
    harness.reset()
    await harness.deliver(message_callback(not_resolved_payload, user_id=did, chat_id=did))
    harness.reset()
    await harness.deliver(
        message_created("Заменили термостат, но шум остался", user_id=did, chat_id=did)
    )

    problem_payload = await _open_card_and_get_button(
        harness, world, button_text=texts.BUTTON_PROBLEM_REMAINS
    )
    harness.reset()
    await harness.deliver(
        message_callback(problem_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    harness.reset()
    await harness.deliver(
        message_created("Компрессор всё ещё шумит", user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("передано" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "in_progress"


async def test_cancel_before_and_after_acceptance(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    cancel_payload = await _open_card_and_get_button(
        harness, world, button_text=texts.BUTTON_CANCEL_REQUEST
    )
    harness.reset()
    await harness.deliver(
        message_callback(cancel_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    target_payload = harness.payload_of(texts.CANCEL_TARGET_STOP)
    harness.reset()
    await harness.deliver(
        message_callback(target_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    harness.reset()
    await harness.deliver(
        message_created("Оборудование заменили", user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("отменена" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "cancelled"


async def test_visit_window_uses_location_timezone(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, location_timezone="Asia/Yekaterinburg")
    await db_session.commit()
    fixed_now = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    set_clock(lambda: fixed_now)
    try:
        await _submit_own_service_request(harness, world)
        await _accept_by_dispatcher(harness, world)

        did = int(world.dispatcher_max_id)
        harness.reset()
        await harness.deliver(message_callback("m:in_progress", user_id=did, chat_id=did))
        propose_payload = harness.payload_of(texts.BUTTON_PROPOSE_VISIT)
        harness.reset()
        await harness.deliver(message_callback(propose_payload, user_id=did, chat_id=did))
        assert any("Asia/Yekaterinburg" in t for t in harness.texts)

        today_payload = harness.payload_of("Сегодня")
        harness.reset()
        await harness.deliver(message_callback(today_payload, user_id=did, chat_id=did))
        slot_payload = harness.payload_of(texts.OFFER_SLOT_MORNING)
        harness.reset()
        await harness.deliver(message_callback(slot_payload, user_id=did, chat_id=did))
        sum_payload = harness.payload_of(texts.OFFER_PRICE_SUM)
        harness.reset()
        await harness.deliver(message_callback(sum_payload, user_id=did, chat_id=did))
        harness.reset()
        await harness.deliver(message_created("1200", user_id=did, chat_id=did))
        harness.reset()
        await harness.deliver(message_created("Диагностика", user_id=did, chat_id=did))

        proposal = (await db_session.execute(select(VisitProposal))).scalars().one()
        assert proposal.visit_window_start == datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        assert proposal.visit_window_end == datetime(2026, 6, 15, 8, 0, tzinfo=UTC)

        manager_uid = int(world.manager_max_id)
        approve_payload = await _open_card_and_get_button(harness, world, button_text=APPROVE_VISIT)
        harness.reset()
        await harness.deliver(
            message_callback(approve_payload, user_id=manager_uid, chat_id=manager_uid)
        )

        harness.reset()
        await harness.deliver(
            message_callback("m:my_requests", user_id=manager_uid, chat_id=manager_uid)
        )
        open_payload = harness.buttons()[0].payload
        harness.reset()
        await harness.deliver(
            message_callback(open_payload, user_id=manager_uid, chat_id=manager_uid)
        )
        assert any("09:00" in t and "Asia/Yekaterinburg" in t for t in harness.texts)
    finally:
        set_clock(None)


async def test_foreign_user_cannot_use_managers_approval_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)
    await _propose_visit(harness, world, amount="1500")

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    approve_payload = await _open_card_and_get_button(harness, world, button_text=APPROVE_VISIT)

    employee_uid = int(world.employee_max_id)
    await harness.deliver(message_created("/start", user_id=employee_uid, chat_id=employee_uid))
    harness.reset()
    await harness.deliver(
        message_callback(approve_payload, user_id=employee_uid, chat_id=employee_uid)
    )
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED

    proposal = (await db_session.execute(select(VisitProposal))).scalars().one()
    assert proposal.status == "pending"
    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status != "scheduled"

    code = approve_payload.split(":", 1)[1]
    action = (
        await db_session.execute(select(BotAction).where(BotAction.code == code))
    ).scalar_one()
    assert action.consumed_at is None


async def test_cancel_after_acceptance_opens_dispute(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)

    manager_uid = int(world.manager_max_id)
    await harness.deliver(message_created("/start", user_id=manager_uid, chat_id=manager_uid))
    cancel_payload = await _open_card_and_get_button(
        harness, world, button_text=texts.BUTTON_CANCEL_REQUEST
    )
    harness.reset()
    await harness.deliver(
        message_callback(cancel_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    target_payload = harness.payload_of(texts.CANCEL_TARGET_STOP)
    harness.reset()
    await harness.deliver(
        message_callback(target_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    harness.reset()
    await harness.deliver(
        message_created("Больше не нужно", user_id=manager_uid, chat_id=manager_uid)
    )
    assert any("отправлен исполнителю" in t for t in harness.texts)

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "cancellation_pending"


async def test_force_cancel_after_silent_deadline(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await _submit_own_service_request(harness, world)
    await _accept_by_dispatcher(harness, world)

    manager_uid = int(world.manager_max_id)
    cancel_payload = await _open_card_and_get_button(
        harness, world, button_text=texts.BUTTON_CANCEL_REQUEST
    )
    harness.reset()
    await harness.deliver(
        message_callback(cancel_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    target_payload = harness.payload_of(texts.CANCEL_TARGET_STOP)
    harness.reset()
    await harness.deliver(
        message_callback(target_payload, user_id=manager_uid, chat_id=manager_uid)
    )
    harness.reset()
    await harness.deliver(
        message_created("Больше не нужно", user_id=manager_uid, chat_id=manager_uid)
    )

    await _open_card_and_get_button(harness, world, button_text=texts.CANCEL_WITHDRAW)
    assert all(b.text != texts.CANCEL_FORCE for b in harness.buttons())

    await db_session.execute(
        update(CancellationRequest).values(
            dispute_deadline_at=datetime.now(UTC) - timedelta(minutes=1)
        )
    )
    await db_session.commit()

    force_payload = await _open_card_and_get_button(harness, world, button_text=texts.CANCEL_FORCE)
    harness.reset()
    await harness.deliver(message_callback(force_payload, user_id=manager_uid, chat_id=manager_uid))
    assert texts.CANCEL_FORCED in harness.texts

    db_session.expire_all()
    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "cancelled"
    cancellation = (await db_session.execute(select(CancellationRequest))).scalars().one()
    assert cancellation.status == "force_closed"
    assert cancellation.disputed is False
