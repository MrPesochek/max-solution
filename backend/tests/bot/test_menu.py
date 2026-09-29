from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import menu, texts
from app.core import ids
from app.db.models import Organization, User
from tests import factories
from tests.bot.conftest import USER_ID, BotHarness, message_callback, message_created


async def _member_of(
    db_session: AsyncSession, name: str, *, role: str = "customer_manager", provider: bool = False
) -> Organization:
    """Пользователь бота (тот же MAX id) с членством в новой организации."""
    user = (
        await db_session.execute(select(User).where(User.max_user_id == str(USER_ID)))
    ).scalar_one_or_none()
    if user is None:
        user = await factories.create_user(db_session, max_user_id=str(USER_ID))
    org = await factories.create_organization(
        db_session, name=name, customer=not provider, provider=provider
    )
    await factories.create_membership(db_session, user, org, role=role)
    await db_session.commit()
    return org


async def test_menu_shows_active_organization_and_customer_items(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _member_of(db_session, "ООО Ромашка")

    await harness.deliver(message_created("/start"))

    assert texts.MENU_HEADER.format(name="ООО Ромашка") in harness.last_text
    titles = {button.text for button in harness.buttons()}
    assert {item.title for item in menu.CUSTOMER_ITEMS} <= titles
    assert texts.OPEN_WEBAPP in titles


async def test_provider_sees_provider_items(harness: BotHarness, db_session: AsyncSession) -> None:
    await _member_of(db_session, "Мастер Плюс", role="provider_admin", provider=True)

    await harness.deliver(message_created("/start"))

    titles = {button.text for button in harness.buttons()}
    assert {item.title for item in menu.PROVIDER_ITEMS} <= titles


def test_every_menu_item_has_handler() -> None:
    """Ни один пункт меню не отвечает «Раздел появится позже» (ТЗ 5.1, 5.2)."""
    missing = [
        item.key
        for item in menu.CUSTOMER_ITEMS + menu.PROVIDER_ITEMS
        if menu.handler_for(item.key) is None
    ]
    assert missing == []


async def test_equipment_section_without_locations(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _member_of(db_session, "ООО Ромашка")
    await harness.deliver(message_created("/start"))
    harness.reset()

    await harness.deliver(message_callback("m:equipment"))

    assert harness.last_text == texts.NO_LOCATIONS
    assert texts.SECTION_LATER not in harness.texts


async def test_organization_section_shows_summary(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    org = await _member_of(db_session, "ООО Ромашка")
    await harness.deliver(message_created("/start"))
    harness.reset()

    await harness.deliver(message_callback(f"m:{menu.ORGANIZATION}"))

    assert "ООО Ромашка" in harness.last_text
    titles = {button.text for button in harness.buttons()}
    assert texts.ORG_MANAGE in titles
    assert ids.encode("organization", org.id)


async def test_several_organizations_require_choice(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _member_of(db_session, "ООО Ромашка")
    second = await _member_of(db_session, "ООО Василёк")

    await harness.deliver(message_created("/start"))
    assert harness.last_text == texts.CHOOSE_ORG

    harness.reset()
    await harness.deliver(message_callback(f"s:{ids.encode('organization', second.id)}"))
    assert texts.ORG_SWITCHED.format(name="ООО Василёк") in harness.last_text


async def test_help_is_answered(harness: BotHarness) -> None:
    await harness.deliver(message_created("/help"))
    assert harness.last_text == texts.HELP
