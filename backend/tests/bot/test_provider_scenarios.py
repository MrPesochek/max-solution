from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import Assignment, Membership
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness


async def _accepted(harness: BotHarness, db_session: AsyncSession) -> rf.BotWorld:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    await flows.accept_by_dispatcher(harness, world)
    return world


async def _assignment(db_session: AsyncSession) -> Assignment:
    assignment = (await db_session.execute(select(Assignment))).scalars().one()
    await db_session.refresh(assignment)
    return assignment


async def test_provider_withdraws_after_acceptance(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_WITHDRAW_ASSIGNMENT), did)
    await flows.say(harness, "Нет запчастей", did)

    assert texts.ASSIGNMENT_WITHDRAWN in harness.texts
    assert (await flows.only_request(db_session)).status == "action_required"
    assignment = await _assignment(db_session)
    assert assignment.withdrawal_reason == "Нет запчастей"

    await flows.open_first_card(harness, int(world.manager_max_id))
    assert "Нет запчастей" in harness.last_text
    titles = {str(b.text) for b in harness.buttons()}
    assert texts.BUTTON_EXTERNAL_SEARCH in titles


async def test_dispatcher_assigns_platform_member(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_FIELD_WORKER), did)
    await flows.press(harness, harness.payload_of("Иван"), did)
    assert texts.FIELD_WORKER_SET in harness.texts

    membership = (
        await db_session.execute(
            select(Membership).where(Membership.organization_id == world.provider_org_id)
        )
    ).scalar_one()
    assert (await _assignment(db_session)).field_worker_membership_id == membership.id


async def test_dispatcher_names_external_master(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_FIELD_WORKER), did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_WORKER_BY_NAME), did)
    await flows.say(harness, "Пётр Сидоров", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_NO_PHONE), did)

    assignment = await _assignment(db_session)
    assert assignment.field_worker_membership_id is None
    assert assignment.field_worker_display_name == "Пётр Сидоров"

    await flows.open_menu(harness, "in_progress", did)
    assert "Пётр Сидоров" in harness.last_text
