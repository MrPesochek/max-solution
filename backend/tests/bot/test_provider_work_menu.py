from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import Assignment, CancellationRequest
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness

APPROVE_VISIT = "Согласовать выезд"


async def _accepted(harness: BotHarness, db_session: AsyncSession) -> rf.BotWorld:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    await flows.accept_by_dispatcher(harness, world)
    return world


async def _scheduled(harness: BotHarness, db_session: AsyncSession) -> rf.BotWorld:
    world = await _accepted(harness, db_session)
    await flows.propose_visit(harness, world, amount="1500")
    manager = int(world.manager_max_id)
    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_starting(APPROVE_VISIT), manager)
    assert (await flows.only_request(db_session)).status == "scheduled"
    return world


async def _assignment(db_session: AsyncSession) -> Assignment:
    assignment = (await db_session.execute(select(Assignment))).scalars().one()
    await db_session.refresh(assignment)
    return assignment


def _titles(harness: BotHarness) -> set[str]:
    return {str(b.text) for b in harness.buttons()}


async def test_warranty_decision_asks_comment_and_saves(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.WARRANTY_YES), did)
    assert harness.last_text == texts.ASK_WARRANTY_COMMENT.format(
        decision=texts.WARRANTY_LABELS["warranty"]
    )
    await flows.say(harness, "Талон действует до декабря", did)

    assert texts.WARRANTY_SAVED in harness.texts
    assignment = await _assignment(db_session)
    assert assignment.warranty_decision == "warranty"
    assert assignment.warranty_decision_comment == "Талон действует до декабря"


async def test_warranty_without_comment_is_not_saved(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.WARRANTY_NO), did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_CANCEL), did)

    assignment = await _assignment(db_session)
    assert assignment.warranty_decision == "not_stated"
    assert texts.WARRANTY_SAVED not in harness.texts


async def test_en_route_button_marks_once(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await _scheduled(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    assert texts.BUTTON_EN_ROUTE in _titles(harness)
    await flows.press(harness, harness.payload_of(texts.BUTTON_EN_ROUTE), did)
    assert texts.EN_ROUTE_MARKED in harness.texts
    assert (await _assignment(db_session)).en_route_at is not None
    assert (await flows.only_request(db_session)).status == "scheduled"

    await flows.open_menu(harness, "in_progress", did)
    assert texts.WORK_CARD_EN_ROUTE in harness.last_text
    assert texts.BUTTON_EN_ROUTE not in _titles(harness)
    assert texts.BUTTON_START_WORK in _titles(harness)


async def test_en_route_not_offered_before_schedule(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _accepted(harness, db_session)
    await flows.open_menu(harness, "in_progress", int(world.dispatcher_max_id))
    assert texts.BUTTON_EN_ROUTE not in _titles(harness)


async def _cancellation_requested(harness: BotHarness, db_session: AsyncSession) -> rf.BotWorld:
    world = await _accepted(harness, db_session)
    manager = int(world.manager_max_id)
    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_CANCEL_REQUEST), manager)
    await flows.press(harness, harness.payload_of(texts.CANCEL_TARGET_STOP), manager)
    await flows.say(harness, "Больше не нужно", manager)
    assert (await flows.only_request(db_session)).status == "cancellation_pending"
    return world


async def test_cancellation_is_answered_from_menu_with_reason(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _cancellation_requested(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    assert "Больше не нужно" in harness.last_text
    titles = _titles(harness)
    assert {texts.BUTTON_ACCEPT_CANCELLATION, texts.BUTTON_DISPUTE_CANCELLATION} <= titles
    assert texts.BUTTON_PROPOSE_VISIT not in titles
    assert texts.WARRANTY_YES not in titles

    await flows.press(harness, harness.payload_of(texts.BUTTON_DISPUTE_CANCELLATION), did)
    assert harness.last_text == texts.ASK_DISPUTE_REASON
    await flows.say(harness, "Запчасть уже заказана под эту заявку", did)

    assert texts.CANCEL_DISPUTE_SENT in harness.texts
    cancellation = (await db_session.execute(select(CancellationRequest))).scalars().one()
    await db_session.refresh(cancellation)
    assert cancellation.provider_response == "Запчасть уже заказана под эту заявку"
    assert cancellation.disputed is True


async def test_cancellation_accept_from_menu(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await _cancellation_requested(harness, db_session)
    did = int(world.dispatcher_max_id)

    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_ACCEPT_CANCELLATION), did)
    assert texts.CANCEL_DONE in harness.texts
    assert (await flows.only_request(db_session)).status == "cancelled"


async def test_completion_reported_is_listed_without_actions(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await _scheduled(harness, db_session)
    did = int(world.dispatcher_max_id)
    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_START_WORK), did)
    await flows.open_menu(harness, "in_progress", did)
    await flows.press(harness, harness.payload_of(texts.BUTTON_REPORT_DONE), did)
    await flows.press(harness, harness.payload_of(texts.OUTCOME_BUTTON_RESOLVED), did)
    await flows.say(harness, "Заменён компрессор", did)
    assert (await flows.only_request(db_session)).status == "completion_reported"

    await flows.open_menu(harness, "in_progress", did)
    assert texts.WORK_CARD_COMPLETION_REPORTED in harness.last_text
    assert _titles(harness) == {texts.BUTTON_OPEN_IN_APP}
