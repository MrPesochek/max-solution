from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import conversations, texts
from app.db.models import BotConversation, MaxUpdate, User
from tests import factories
from tests.bot.conftest import BotHarness, message_callback, message_created

GROUP_CHAT_ID = 900


def _in_group(event: dict[str, Any]) -> dict[str, Any]:
    event["message"]["recipient"] = {"chat_id": GROUP_CHAT_ID, "chat_type": "chat"}
    return event


async def test_group_message_gets_short_reply_without_data(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await harness.deliver(_in_group(message_created("/start")))
    await harness.deliver(_in_group(message_created("Мои заявки")))

    assert harness.texts == [texts.PERSONAL_ONLY, texts.PERSONAL_ONLY]
    assert all(call.attachments is None for call in harness.transport.sent_messages)
    assert all(call.chat_id == GROUP_CHAT_ID for call in harness.transport.sent_messages)
    assert (
        await db_session.execute(select(func.count()).select_from(BotConversation))
    ).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar_one() == 0


async def test_group_callback_is_not_processed(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await harness.deliver(_in_group(message_callback("m:my_requests")))

    assert harness.transport.sent_messages == []
    (answer,) = harness.transport.answered_callbacks
    assert answer.notification == texts.PERSONAL_ONLY
    assert (
        await db_session.execute(select(func.count()).select_from(BotConversation))
    ).scalar_one() == 0


async def test_chat_of_another_user_drops_selected_membership(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    first = await factories.create_user(db_session)
    second = await factories.create_user(db_session)
    org = await factories.create_organization(db_session)
    membership = await factories.create_membership(db_session, first, org)
    row = BotConversation(
        user_id=first.id,
        max_chat_id="500",
        current_step="request.symptom",
        context={"draft": "x"},
        active_organization_id=org.id,
        active_membership_id=membership.id,
    )
    db_session.add(row)
    await db_session.flush()

    state = await conversations.load_or_create(db_session, second.id, "500")

    assert state.user_id == second.id
    assert state.active_membership_id is None
    assert state.active_organization_id is None
    assert state.current_step is None
    assert state.context == {}


async def _stored(db_session: AsyncSession) -> list[MaxUpdate]:
    rows = list((await db_session.execute(select(MaxUpdate))).scalars())
    for row in rows:
        await db_session.refresh(row)
    return rows


async def test_group_event_is_stored_without_payload(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await harness.deliver(_in_group(message_created("Телефон соседа +79990001122")))
    (row,) = await _stored(db_session)
    assert row.raw_payload == {}
    assert row.max_update_id


async def test_processed_event_payload_is_cleared(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await harness.deliver(message_created("/start"))
    (row,) = await _stored(db_session)
    assert row.processed_at is not None and row.processing_error is None
    assert row.raw_payload == {}


async def test_failed_event_keeps_payload_for_analysis(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("сбой обработчика")

    monkeypatch.setattr(harness.runtime.dispatcher, "handle", broken)
    outcome = await harness.deliver(message_created("/start"))
    assert outcome.failed
    (row,) = await _stored(db_session)
    assert row.processing_error == "RuntimeError"
    assert row.raw_payload["update_type"] == "message_created"
