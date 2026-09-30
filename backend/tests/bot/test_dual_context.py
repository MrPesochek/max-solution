import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import menu, texts
from app.core import ids
from app.db.models import BotAction, Membership, Organization, User, VisitProposal
from tests import factories
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import USER_ID, BotHarness, message_callback, message_created


async def test_switching_side_within_one_organization(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    user = await factories.create_user(db_session, max_user_id=str(USER_ID))
    org = await factories.create_organization(db_session, name="Двойная", provider=True)
    await factories.create_membership(db_session, user, org, role="customer_manager")
    await factories.create_membership(db_session, user, org, role="provider_admin")
    await db_session.commit()

    await harness.deliver(message_created("/start"))
    assert harness.last_text == texts.CHOOSE_ORG
    choice = f"Двойная · {texts.ORG_KIND_PROVIDER}"
    assert choice in {button.text for button in harness.buttons()}

    payload = harness.payload_of(choice)
    harness.reset()
    await harness.deliver(message_callback(payload))

    assert texts.ORG_SWITCHED.format(name="Двойная") in harness.last_text
    assert texts.MENU_SIDE.format(side=texts.ORG_KIND_PROVIDER) in harness.last_text
    titles = {button.text for button in harness.buttons()}
    assert {item.title for item in menu.PROVIDER_ITEMS} <= titles
    assert texts.CHANGE_ORG in titles


async def _dual_manager_notification(
    harness: BotHarness, db_session: AsyncSession
) -> tuple[str, int, uuid.UUID]:
    from app.worker import notification_templates as templates

    world = await rf.build(db_session)
    manager_user = await flows.user_id_of(db_session, world.manager_max_id)
    customer = await db_session.get(Organization, world.customer_org_id)
    assert customer is not None
    customer.is_provider = True
    manager_user_row = await db_session.get(User, manager_user)
    assert manager_user_row is not None
    await factories.create_membership(db_session, manager_user_row, customer, role="provider_admin")
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    await flows.accept_by_dispatcher(harness, world)
    await flows.propose_visit(harness, world, amount="1500")

    uid = int(world.manager_max_id)
    await flows.say(harness, "/start", uid)
    await flows.press(harness, harness.payload_of(f"Сеть кафе · {texts.ORG_KIND_PROVIDER}"), uid)

    manager_membership = (
        await db_session.execute(
            select(Membership.id).where(
                Membership.user_id == manager_user, Membership.role == "customer_manager"
            )
        )
    ).scalar_one()
    request = await flows.only_request(db_session)
    proposal = (await db_session.execute(select(VisitProposal))).scalars().one()
    message = await templates.render(
        db_session,
        "visit_proposal.created",
        {
            "request_id": ids.encode("request", request.id),
            "visit_proposal_id": ids.encode("visit_proposal", proposal.id),
            "proposal_version": proposal.version,
        },
        recipient_user_id=manager_user,
        recipient_membership_id=manager_membership,
        now=request.updated_at,
    )
    await db_session.commit()
    approve = message.attachments[0].payload.buttons[0][0].payload
    return str(approve), uid, manager_membership


async def test_notification_button_acts_as_recipient_membership(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    approve, uid, _ = await _dual_manager_notification(harness, db_session)

    await flows.press(harness, approve, uid)

    assert texts.VISIT_PROPOSAL_APPROVED in harness.texts
    assert (await flows.only_request(db_session)).status == "scheduled"


async def test_revoked_recipient_membership_keeps_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    approve, uid, membership_id = await _dual_manager_notification(harness, db_session)
    await db_session.execute(
        update(Membership).where(Membership.id == membership_id).values(status="revoked")
    )
    await db_session.commit()

    await flows.press(harness, approve, uid)

    assert harness.transport.answered_callbacks[-1].notification == texts.ROLE_UNAVAILABLE
    assert (await flows.only_request(db_session)).status == "accepted"
    code = approve.split(":", 1)[1]
    action = (
        await db_session.execute(select(BotAction).where(BotAction.code == code))
    ).scalar_one()
    await db_session.refresh(action)
    assert action.consumed_at is None
