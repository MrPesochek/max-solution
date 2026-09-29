from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import Assignment, District, Location, ProviderServiceArea, RepairRequest
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness


async def test_manager_revokes_own_service_and_publishes(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    manager = int(world.manager_max_id)

    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_REVOKE_ASSIGNMENT), manager)
    await flows.say(harness, "Сервис не отвечает", manager)
    assert texts.ASSIGNMENT_REVOKED in harness.texts
    request = await flows.only_request(db_session)
    assert request.status == "action_required"
    assignment = (await db_session.execute(select(Assignment))).scalars().one()
    await db_session.refresh(assignment)
    assert assignment.state == "revoked"

    titles = {str(b.text) for b in harness.buttons()}
    assert {texts.BUTTON_EXTERNAL_SEARCH, texts.BUTTON_RESEND_OWN} <= titles
    await flows.press(harness, harness.payload_of(texts.BUTTON_EXTERNAL_SEARCH), manager)
    preview = harness.last_text
    assert "увидят исполнители" in preview
    assert "ул. Примерная" not in preview
    assert texts.PUBLISH_PHOTOS_NONE in preview

    await flows.press(harness, harness.payload_of(texts.BUTTON_PUBLISH), manager)
    assert any("опубликована" in t for t in harness.texts)
    assert (await flows.only_request(db_session)).status == "searching"


async def test_no_providers_then_repeat_with_other_district(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    location = await db_session.get(Location, world.location_id)
    assert location is not None
    other = (
        (
            await db_session.execute(
                select(District).where(
                    District.city_id == location.city_id, District.id != location.district_id
                )
            )
        )
        .scalars()
        .first()
    )
    assert other is not None
    await db_session.execute(
        update(ProviderServiceArea)
        .where(ProviderServiceArea.provider_org_id == world.provider_org_id)
        .values(district_id=other.id)
    )
    await db_session.commit()

    await flows.submit_for_approval(harness, world)
    manager = int(world.manager_max_id)
    await flows.say(harness, "/start", manager)
    await flows.open_menu(harness, "find_provider", manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_PUBLISH), manager)
    assert texts.PUBLISH_NO_PROVIDERS in harness.texts
    assert (await flows.only_request(db_session)).status == "action_required"

    await flows.press(harness, harness.payload_of(texts.BUTTON_REPEAT_SEARCH), manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_CHANGE_DISTRICT), manager)
    await flows.press(harness, harness.payload_of(other.name), manager)
    assert other.name in harness.last_text
    await flows.press(harness, harness.payload_of(texts.BUTTON_PUBLISH), manager)
    assert any("опубликована" in t for t in harness.texts)
    assert (await flows.only_request(db_session)).status == "searching"


async def test_manager_returns_draft_for_rework(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session, with_binding=False)
    await db_session.commit()
    await flows.submit_for_approval(harness, world)
    manager = int(world.manager_max_id)

    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_RETURN_TO_DRAFT), manager)
    await flows.say(harness, "Добавьте фото шильдика", manager)
    assert texts.RETURNED_TO_DRAFT in harness.texts
    assert (await flows.only_request(db_session)).status == "draft"


async def test_followup_request_after_cancel(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    manager = int(world.manager_max_id)

    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_CANCEL_REQUEST), manager)
    await flows.press(harness, harness.payload_of(texts.CANCEL_TARGET_STOP), manager)
    await flows.say(harness, "Уже не нужно", manager)
    assert (await flows.only_request(db_session)).status == "cancelled"

    await flows.open_menu(harness, "my_requests", manager)
    await flows.press(harness, harness.payload_of(texts.REQUESTS_TAB_DONE), manager)
    await flows.press(harness, str(harness.buttons()[0].payload), manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_FOLLOWUP), manager)
    assert any("связанный" in t for t in harness.texts)
    assert harness.last_text == texts.ASK_SYMPTOMS

    requests = (
        (await db_session.execute(select(RepairRequest).order_by(RepairRequest.created_at)))
        .scalars()
        .all()
    )
    assert len(requests) == 2
    assert requests[1].status == "draft"
    assert requests[1].parent_request_id == requests[0].id

    await flows.say(harness, "Снова не морозит", manager)
    await db_session.refresh(requests[1])
    assert requests[1].symptom_description == "Снова не морозит"
