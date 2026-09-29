from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import (
    District,
    Location,
    ProviderServiceArea,
    RepairRequest,
    RequestEvent,
    RequestPublicCard,
)
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness


async def _details_events(db_session: AsyncSession) -> int:
    return (
        await db_session.execute(
            select(func.count())
            .select_from(RequestEvent)
            .where(RequestEvent.event_type == "RequestDetailsUpdated")
        )
    ).scalar_one()


async def test_manager_changes_description_and_urgency(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    await flows.submit_own_service(harness, world)
    manager = int(world.manager_max_id)

    await flows.open_first_card(harness, manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_REVOKE_ASSIGNMENT), manager)
    await flows.say(harness, "Сервис не отвечает", manager)
    assert (await flows.only_request(db_session)).status == "action_required"
    await flows.press(harness, harness.payload_of(texts.BUTTON_CHANGE_TERMS), manager)
    titles = {str(b.text) for b in harness.buttons()}
    assert texts.BUTTON_CHANGE_DISTRICT not in titles
    assert texts.BUTTON_DETAILS_SAVE not in titles

    await flows.press(harness, harness.payload_of(texts.BUTTON_DETAILS_URGENCY), manager)
    await flows.press(harness, harness.payload_of(texts.URGENCY_CRITICAL), manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_DETAILS_DESCRIPTION), manager)
    await flows.say(harness, "Не морозит и течёт", manager)
    assert texts.DETAILS_CHANGED in harness.last_text
    save = harness.payload_of(texts.BUTTON_DETAILS_SAVE)
    await flows.press(harness, save, manager)
    assert texts.DETAILS_SAVED in harness.texts

    request = await flows.only_request(db_session)
    assert request.status == "action_required"
    assert request.urgency == "critical"
    assert request.symptom_description == "Не морозит и течёт"
    assert await _details_events(db_session) == 1

    await flows.press(harness, save, manager)
    assert await _details_events(db_session) == 1


async def test_manager_changes_district_after_empty_search(
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
    assert (await flows.only_request(db_session)).status == "action_required"

    await flows.press(harness, harness.payload_of(texts.BUTTON_CHANGE_TERMS), manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_CHANGE_DISTRICT), manager)
    await flows.press(harness, harness.payload_of(other.name), manager)
    assert other.name in harness.last_text
    await flows.press(harness, harness.payload_of(texts.BUTTON_DETAILS_DESCRIPTION), manager)
    await flows.say(harness, "Шкаф не держит холод", manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_DETAILS_SAVE), manager)
    assert texts.DETAILS_SAVED in harness.texts

    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    card = (
        await db_session.execute(
            select(RequestPublicCard).where(RequestPublicCard.request_id == request.id)
        )
    ).scalar_one()
    await db_session.refresh(card)
    assert card.district_id == other.id
    assert card.published_description == "Шкаф не держит холод"

    await flows.press(harness, harness.payload_of(texts.BUTTON_REPEAT_SEARCH), manager)
    await flows.press(harness, harness.payload_of(texts.BUTTON_PUBLISH), manager)
    assert any("опубликована" in t for t in harness.texts)
    assert (await flows.only_request(db_session)).status == "searching"
