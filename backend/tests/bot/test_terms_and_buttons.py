import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.core import ids
from app.core.money import format_money, format_price
from app.db.models import BotAction, BotConversation, Message, Offer, VisitProposal
from app.modules.requests import api as requests_api
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness, message_created

NBSP = " "


def test_money_keeps_kopecks_and_groups_thousands() -> None:
    assert format_money(150000, "RUB") == f"1{NBSP}500{NBSP}₽"
    assert format_money(150050, "RUB") == f"1{NBSP}500,50{NBSP}₽"
    assert format_money(12345678905, "RUB") == f"123{NBSP}456{NBSP}789,05{NBSP}₽"
    assert format_money(99, "USD") == f"0,99{NBSP}USD"


def test_price_unknown_and_zero_are_explicit() -> None:
    assert format_price(None) == "стоимость уточняется"
    assert format_price(0, "RUB", "гарантийный случай") == (
        f"0{NBSP}₽ (основание: гарантийный случай)"
    )


async def _visit_ready(harness: BotHarness, db_session: AsyncSession, amount: str) -> rf.BotWorld:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    await flows.accept_by_dispatcher(harness, world)
    await flows.propose_visit(harness, world, amount=amount)
    return world


async def test_card_shows_terms_and_version_next_to_approve(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _visit_ready(harness, db_session, "1500,50")
    await flows.open_first_card(harness, int(world.manager_max_id))

    card = harness.last_text
    assert "Условия выезда" in card and "версия 1" in card
    assert f"1{NBSP}500,50{NBSP}₽" in card
    assert "Диагностика компрессора" in card
    assert "Время:" in card and "Действует до:" in card
    titles = [str(b.text) for b in harness.buttons()]
    assert "Согласовать выезд (версия 1)" in titles

    code = harness.payload_starting("Согласовать выезд").split(":", 1)[1]
    action = (
        await db_session.execute(select(BotAction).where(BotAction.code == code))
    ).scalar_one()
    proposal = (await db_session.execute(select(VisitProposal))).scalars().one()
    assert action.proposal_version == proposal.version == 1


async def test_employee_sees_terms_without_approve_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _visit_ready(harness, db_session, "900")
    await flows.open_first_card(harness, int(world.employee_max_id))

    assert "Условия выезда" in harness.last_text
    assert texts.APPROVAL_BY_MANAGER in harness.last_text
    assert not any(str(b.text).startswith("Согласовать") for b in harness.buttons())


async def test_notification_shows_kopecks(harness: BotHarness, db_session: AsyncSession) -> None:
    from app.worker import notification_templates as templates

    world = await _visit_ready(harness, db_session, "1500,50")
    request = await flows.only_request(db_session)
    proposal = (await db_session.execute(select(VisitProposal))).scalars().one()
    manager = await flows.user_id_of(db_session, world.manager_max_id)
    message = await templates.render(
        db_session,
        "visit_proposal.created",
        {
            "request_id": ids.encode("request", request.id),
            "visit_proposal_id": ids.encode("visit_proposal", proposal.id),
            "proposal_version": proposal.version,
        },
        recipient_user_id=manager,
        now=request.updated_at,
    )
    assert f"1{NBSP}500,50{NBSP}₽" in message.text
    assert "версия 1" in message.text


async def test_transient_failure_does_not_burn_button(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _visit_ready(harness, db_session, "1500")
    manager_uid = int(world.manager_max_id)
    await flows.open_first_card(harness, manager_uid)
    approve = harness.payload_starting("Согласовать выезд")

    original = requests_api.approve_visit_proposal
    calls = {"n": 0}

    async def flaky(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("база недоступна")
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(requests_api, "approve_visit_proposal", flaky)

    await flows.press(harness, approve, manager_uid)
    assert texts.TRY_AGAIN in harness.texts
    assert (await flows.only_request(db_session)).status == "accepted"

    await flows.press(harness, approve, manager_uid)
    assert texts.VISIT_PROPOSAL_APPROVED in harness.texts
    assert (await flows.only_request(db_session)).status == "scheduled"


async def test_used_button_shows_current_card(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _visit_ready(harness, db_session, "1500")
    manager_uid = int(world.manager_max_id)
    await flows.open_first_card(harness, manager_uid)
    approve = harness.payload_starting("Согласовать выезд")
    await flows.press(harness, approve, manager_uid)

    await flows.press(harness, approve, manager_uid)
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    request = await flows.only_request(db_session)
    assert texts.REQUEST_CARD_HEADER.format(number=request.request_number) in harness.last_text
    assert texts.STATUS_LABELS["scheduled"] in harness.last_text
    assert texts.MENU_PROMPT not in harness.last_text


async def test_repeated_final_answer_posts_one_message(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Второй обработчик с тем же состоянием диалога (гонка) не пишет второе сообщение."""
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    await flows.accept_by_dispatcher(harness, world)

    did = int(world.manager_max_id)
    request = await flows.only_request(db_session)
    await _start_reply(harness, db_session, did, request.id)

    row = (
        await db_session.execute(
            select(BotConversation).where(BotConversation.max_chat_id == str(did))
        )
    ).scalar_one()
    await db_session.refresh(row)
    step, context = row.current_step, dict(row.context)
    assert step == "req_reply:body"

    await flows.say(harness, "Будем завтра к 10", did)
    row.current_step, row.context = step, context
    await db_session.commit()
    await flows.say(harness, "Будем завтра к 10", did)

    messages = (await db_session.execute(select(Message))).scalars().all()
    assert [m.body for m in messages].count("Будем завтра к 10") == 1


async def test_parallel_submit_creates_one_offer(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await flows.submit_for_approval(harness, world)
    manager_uid = int(world.manager_max_id)
    await flows.say(harness, "/start", manager_uid)
    await flows.open_menu(harness, "find_provider", manager_uid)
    await flows.press(harness, harness.payload_of(texts.BUTTON_PUBLISH), manager_uid)

    did = int(world.dispatcher_max_id)
    await flows.say(harness, "/start", did)
    await flows.open_menu(harness, "available", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_RESPOND), did)
    await flows.press(harness, harness.payload_of("Завтра"), did)
    await flows.press(harness, harness.payload_of(texts.OFFER_SLOT_DAY), did)
    await flows.press(harness, harness.payload_of(texts.OFFER_PRICE_LATER), did)

    harness.reset()
    await asyncio.gather(
        harness.deliver(message_created("Диагностика", user_id=did, chat_id=did)),
        harness.deliver(message_created("Диагностика", user_id=did, chat_id=did)),
    )
    offers = (await db_session.execute(select(Offer))).scalars().all()
    assert len(offers) == 1
    assert harness.texts.count(texts.OFFER_SUBMITTED) == 1


async def _start_reply(
    harness: BotHarness, db_session: AsyncSession, uid: int, request_id: uuid.UUID
) -> None:
    from app.worker import notification_templates as templates

    user = await flows.user_id_of(db_session, str(uid))
    message = await templates.render(
        db_session,
        "message.created",
        {"request_id": ids.encode("request", request_id)},
        recipient_user_id=user,
        now=(await flows.only_request(db_session)).updated_at,
    )
    await db_session.commit()
    reply = message.attachments[0].payload.buttons[0][0].payload  # type: ignore[union-attr]
    await flows.say(harness, "/start", uid)
    await flows.press(harness, reply, uid)
