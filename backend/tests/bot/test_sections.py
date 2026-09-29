from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import Equipment, Location, Organization, ProviderProfile, RepairRequest
from tests import factories
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness
from tests.requests import factories as req_factories

ADMIN_ID = 91004


async def _provider_admin(db_session: AsyncSession, world: rf.BotWorld) -> int:
    provider = await db_session.get(Organization, world.provider_org_id)
    assert provider is not None
    user = await factories.create_user(db_session, max_user_id=str(ADMIN_ID), display_name="Админ")
    await factories.create_membership(db_session, user, provider, role="provider_admin")
    await db_session.commit()
    return ADMIN_ID


async def test_equipment_card_and_new_request(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    manager = int(world.manager_max_id)

    await flows.say(harness, "/start", manager)
    await flows.open_menu(harness, "equipment", manager)
    await flows.press(harness, harness.payload_of("Кафе на Ленина"), manager)
    await flows.press(harness, harness.payload_of("Полюс ВХС-1"), manager)
    card = harness.last_text
    assert "Холод-Сервис" in card and "подтверждена" in card
    assert texts.EQUIPMENT_NEW_REQUEST_OWN in card
    assert texts.BUTTON_BACK in {str(b.text) for b in harness.buttons()}

    await flows.press(harness, harness.payload_of(texts.BUTTON_NEW_REQUEST), manager)
    assert harness.last_text == texts.ASK_SYMPTOMS
    request = (await db_session.execute(select(RepairRequest))).scalars().one()
    assert request.status == "draft"
    assert request.equipment_id == world.equipment_id
    assert request.route == "own_service"


async def test_equipment_list_is_paged(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await rf.build(db_session)
    customer = await db_session.get(Organization, world.customer_org_id)
    location = await db_session.get(Location, world.location_id)
    assert customer is not None and location is not None
    category_id = await req_factories.category_by_index(db_session, 0)
    for index in range(8):
        await req_factories.create_equipment(
            db_session, customer, location, category_id=category_id, brand=f"Марка{index}"
        )
    await db_session.commit()
    manager = int(world.manager_max_id)

    await flows.say(harness, "/start", manager)
    await flows.open_menu(harness, "equipment", manager)
    await flows.press(harness, harness.payload_of("Кафе на Ленина"), manager)
    first_page = [str(b.text) for b in harness.buttons()]
    assert texts.BUTTON_MORE in first_page

    await flows.press(harness, harness.payload_of(texts.BUTTON_MORE), manager)
    second_page = [str(b.text) for b in harness.buttons()]
    assert texts.BUTTON_PREV in second_page
    total = (await db_session.execute(select(Equipment))).scalars().all()
    shown = {t for t in first_page + second_page if t not in {texts.BUTTON_MORE, texts.BUTTON_PREV}}
    assert len(total) <= len(shown)


async def test_admin_toggles_accepting_new_requests(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    admin = await _provider_admin(db_session, world)
    profile = (
        await db_session.execute(
            select(ProviderProfile).where(ProviderProfile.organization_id == world.provider_org_id)
        )
    ).scalar_one()
    was_accepting = profile.accepting_new_requests

    await flows.say(harness, "/start", admin)
    await flows.open_menu(harness, "profile", admin)
    assert texts.PROFILE_STATUS_LABELS["active"] in harness.last_text
    toggle = texts.BUTTON_ACCEPTING_OFF if was_accepting else texts.BUTTON_ACCEPTING_ON
    await flows.press(harness, harness.payload_of(toggle), admin)

    await db_session.refresh(profile)
    assert profile.accepting_new_requests is (not was_accepting)


async def test_dispatcher_sees_profile_without_toggle(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    did = int(world.dispatcher_max_id)

    await flows.say(harness, "/start", did)
    await flows.open_menu(harness, "profile", did)
    assert texts.PROFILE_ADMIN_ONLY in harness.last_text
    titles = {str(b.text) for b in harness.buttons()}
    assert not titles & {texts.BUTTON_ACCEPTING_ON, texts.BUTTON_ACCEPTING_OFF}


async def test_integration_status_for_admin(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await rf.build(db_session)
    admin = await _provider_admin(db_session, world)
    provider = await db_session.get(Organization, world.provider_org_id)
    assert provider is not None

    await flows.say(harness, "/start", admin)
    await flows.open_menu(harness, "integration", admin)
    assert texts.INTEGRATION_NOT_CONNECTED in harness.last_text

    client, _ = await factories.create_integration_client(db_session, provider)
    subscription = await factories.create_webhook_subscription(db_session, client)
    event = await factories.create_integration_event(db_session, provider)
    delivery = await factories.create_webhook_delivery(
        db_session, event, subscription, state="failed", attempt_count=5
    )
    delivery.last_error = "connection refused"
    await db_session.commit()

    await flows.open_menu(harness, "integration", admin)
    text = harness.last_text
    assert texts.INTEGRATION_CONNECTED in text
    assert texts.INTEGRATION_KEYS.format(count=1) in text
    assert "connection refused" in text
    assert texts.INTEGRATION_SETUP in {str(b.text) for b in harness.buttons()}


async def test_integration_hidden_from_dispatcher(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    did = int(world.dispatcher_max_id)

    await flows.say(harness, "/start", did)
    await flows.open_menu(harness, "integration", did)
    assert harness.last_text == texts.INTEGRATION_ADMIN_ONLY
