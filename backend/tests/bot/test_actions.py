from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.core.clock import utcnow
from app.db.models import BotAction, Invitation, Membership
from tests import factories
from tests.bot.conftest import BotHarness, message_callback, message_created


async def _offer_invitation(harness: BotHarness, db_session: AsyncSession) -> str:
    org = await factories.create_organization(db_session, name="ООО Ромашка")
    _, token = await factories.create_invitation(db_session, org)
    await db_session.commit()
    await harness.deliver(message_created(f"/start inv_{token}"))
    payload = harness.payload_of(texts.INVITATION_ACCEPT)
    harness.reset()
    return payload


async def test_second_press_does_not_duplicate(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    payload = await _offer_invitation(harness, db_session)

    await harness.deliver(message_callback(payload))
    harness.reset()
    await harness.deliver(message_callback(payload))

    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    memberships = (await db_session.execute(select(Membership))).scalars().all()
    assert len(memberships) == 1


async def test_expired_action_is_outdated(harness: BotHarness, db_session: AsyncSession) -> None:
    payload = await _offer_invitation(harness, db_session)
    action = (await db_session.execute(select(BotAction))).scalar_one()
    action.expires_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()

    await harness.deliver(message_callback(payload))

    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    invitation = (await db_session.execute(select(Invitation))).scalar_one()
    assert invitation.status == "pending"


async def test_unknown_code_is_outdated(harness: BotHarness) -> None:
    await harness.deliver(message_callback("a:no-such-code"))
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED


async def test_unparsable_payload_is_outdated(harness: BotHarness) -> None:
    await harness.deliver(message_callback("garbage"))
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED


async def test_action_is_consumed_once(harness: BotHarness, db_session: AsyncSession) -> None:
    payload = await _offer_invitation(harness, db_session)
    await harness.deliver(message_callback(payload))

    action = (await db_session.execute(select(BotAction))).scalar_one()
    assert action.consumed_at is not None
