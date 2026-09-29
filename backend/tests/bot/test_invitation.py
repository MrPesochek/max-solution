from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.core.clock import utcnow
from app.db.models import BotAction, Invitation, Membership
from tests import factories
from tests.bot.conftest import (
    USER_ID,
    BotHarness,
    bot_started,
    message_callback,
    message_created,
)


async def _invitation(
    db_session: AsyncSession, *, role: str = "customer_employee", **kwargs: object
) -> tuple[Invitation, str]:
    org = await factories.create_organization(db_session, name="ООО Ромашка")
    invitation, token = await factories.create_invitation(db_session, org, role=role, **kwargs)  # type: ignore[arg-type]
    await db_session.commit()
    return invitation, token


async def test_preview_does_not_consume_invitation(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    invitation, token = await _invitation(db_session)

    await harness.deliver(bot_started(payload=f"inv_{token}"))

    assert "ООО Ромашка" in harness.last_text
    await db_session.refresh(invitation)
    assert invitation.status == "pending"
    assert invitation.accepted_at is None
    assert not (await db_session.execute(select(Membership))).scalars().all()


async def test_accept_button_consumes_invitation(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Именное приглашение адресату: доступ открывается сразу (ТЗ 6.5.4, 6.7)."""
    invitation, token = await _invitation(db_session, recipient_max_user_id=str(USER_ID))
    await harness.deliver(message_created(f"/start inv_{token}"))
    payload = harness.payload_of(texts.INVITATION_ACCEPT)

    await harness.deliver(message_callback(payload))

    await db_session.refresh(invitation)
    assert invitation.status == "accepted"
    membership = (await db_session.execute(select(Membership))).scalar_one()
    assert membership.role == "customer_employee"
    assert membership.status == "active"
    assert any(
        texts.INVITATION_ACCEPTED.format(organization="ООО Ромашка") in t for t in harness.texts
    )


async def test_accept_without_recipient_waits_for_manager(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Приглашение без адресата: членство ждёт подтверждения руководителем."""
    invitation, token = await _invitation(db_session)
    await harness.deliver(message_created(f"/start inv_{token}"))
    payload = harness.payload_of(texts.INVITATION_ACCEPT)

    await harness.deliver(message_callback(payload))

    await db_session.refresh(invitation)
    assert invitation.status == "accepted"
    membership = (await db_session.execute(select(Membership))).scalar_one()
    assert membership.status == "pending"
    assert texts.INVITATION_PENDING.format(organization="ООО Ромашка") in harness.texts


async def test_named_invitation_of_other_user_is_not_consumed(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    invitation, token = await _invitation(db_session, recipient_max_user_id="someone-else")
    await harness.deliver(message_created(f"/start inv_{token}"))
    payload = harness.payload_of(texts.INVITATION_ACCEPT)

    await harness.deliver(message_callback(payload))

    await db_session.refresh(invitation)
    assert invitation.status == "pending"
    assert (await db_session.execute(select(Membership))).scalars().all() == []


async def test_token_is_not_kept_in_conversation(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Токен нигде не сохраняется: кнопку подтверждает строка `bot_actions`."""
    invitation, token = await _invitation(db_session)
    await harness.deliver(message_created(f"/start inv_{token}"))

    action = (await db_session.execute(select(BotAction))).scalar_one()
    assert action.action_type == "invitation.accept"
    assert action.object_id == invitation.id
    assert token not in action.code

    from app.db.models import BotConversation

    conversation = (await db_session.execute(select(BotConversation))).scalar_one()
    assert token not in str(conversation.context)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("accepted", texts.INVITATION_USED), ("revoked", texts.INVITATION_REVOKED)],
)
async def test_used_and_revoked_invitations_are_explained(
    harness: BotHarness, db_session: AsyncSession, status: str, expected: str
) -> None:
    _, token = await _invitation(db_session, status=status)

    await harness.deliver(message_created(f"/start inv_{token}"))

    assert expected in harness.texts


async def test_expired_invitation_is_explained(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    _, token = await _invitation(db_session, expires_at=utcnow() - timedelta(hours=1))

    await harness.deliver(message_created(f"/start inv_{token}"))

    assert texts.INVITATION_EXPIRED in harness.texts


async def test_unknown_token_is_explained(harness: BotHarness) -> None:
    await harness.deliver(message_created("/start inv_unknown-token-value"))
    assert texts.INVITATION_UNKNOWN in harness.texts


async def test_foreign_accept_button_is_rejected(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Пересланная кнопка не работает: адресат проверяется по отправителю события."""
    invitation, token = await _invitation(db_session)
    await harness.deliver(message_created(f"/start inv_{token}"))
    payload = harness.payload_of(texts.INVITATION_ACCEPT)
    harness.reset()

    await harness.deliver(message_callback(payload, user_id=999, chat_id=999))

    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    await db_session.refresh(invitation)
    assert invitation.status == "pending"
    assert (await db_session.execute(select(Membership))).scalars().all() == []
