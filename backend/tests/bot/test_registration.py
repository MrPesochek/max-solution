from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import (
    BotConversation,
    Location,
    Membership,
    Organization,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
)
from tests.bot.conftest import (
    BotHarness,
    build_harness,
    contact_message,
    message_callback,
    message_created,
)


async def _open_registration(harness: BotHarness, kind: str = "new_customer") -> None:
    await harness.deliver(message_created("/start"))
    await harness.deliver(message_callback(f"m:{kind}"))


async def _city_payload(harness: BotHarness) -> str:
    for button in harness.buttons():
        payload = str(button.payload)
        if payload.startswith("d:city:city_"):
            return payload
    raise AssertionError("кнопка города не найдена")


async def test_customer_registration_creates_organization_with_location(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _open_registration(harness)
    await harness.deliver(message_created("ООО Ромашка"))
    await harness.deliver(contact_message("+79990000000"))
    await harness.deliver(message_callback(await _city_payload(harness)))
    district = next(
        (str(b.payload) for b in harness.buttons() if str(b.payload).startswith("d:district:dst_")),
        None,
    )
    if district is not None:
        await harness.deliver(message_callback(district))
    await harness.deliver(message_created("ул. Тестовая, 1"))

    org = (await db_session.execute(select(Organization))).scalar_one()
    assert org.display_name == "ООО Ромашка"
    assert org.is_customer is True
    assert org.contact_phone == "+79990000000"

    membership = (await db_session.execute(select(Membership))).scalar_one()
    assert membership.role == "customer_manager"
    assert membership.status == "active"

    location = (await db_session.execute(select(Location))).scalar_one()
    assert location.address == "ул. Тестовая, 1"
    assert location.customer_org_id == org.id

    conversation = (await db_session.execute(select(BotConversation))).scalar_one()
    assert conversation.current_step is None
    assert conversation.active_organization_id == org.id


async def test_provider_registration_skips_location(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _open_registration(harness, "new_provider")
    await harness.deliver(message_created("Мастер Плюс"))
    await harness.deliver(message_created("+79991112233"))

    org = (await db_session.execute(select(Organization))).scalar_one()
    assert org.is_provider is True
    assert not (await db_session.execute(select(Location))).scalars().all()
    assert texts.ORG_CREATED_PROVIDER.format(name="Мастер Плюс") in harness.texts


async def test_back_returns_to_previous_step(harness: BotHarness) -> None:
    await _open_registration(harness)
    await harness.deliver(message_created("ООО Ромашка"))
    assert harness.last_text == texts.ASK_PHONE

    await harness.deliver(message_callback("d:phone:back"))
    assert harness.last_text == texts.ASK_ORG_NAME


async def test_cancel_closes_dialog(harness: BotHarness, db_session: AsyncSession) -> None:
    await _open_registration(harness)
    await harness.deliver(message_callback("d:name:cancel"))

    assert harness.last_text == texts.CANCELLED
    conversation = (await db_session.execute(select(BotConversation))).scalar_one()
    assert conversation.current_step is None

    await harness.deliver(message_created("/cancel"))
    assert harness.last_text == texts.NOTHING_TO_CANCEL


async def test_dialog_survives_restart(harness: BotHarness, db_session: AsyncSession) -> None:
    await _open_registration(harness)
    await harness.deliver(message_created("ООО Ромашка"))

    restarted = build_harness()
    await restarted.deliver(contact_message("+79990000000"))
    assert restarted.last_text == texts.ASK_CITY

    conversation = (await db_session.execute(select(BotConversation))).scalar_one()
    assert conversation.current_step == "org_reg:city"
    assert conversation.context["data"]["name"] == "ООО Ромашка"


async def test_stale_dialog_button_is_outdated(harness: BotHarness) -> None:
    await _open_registration(harness)
    await harness.deliver(message_created("ООО Ромашка"))
    harness.reset()

    await harness.deliver(message_callback("d:name:cancel"))
    assert harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    assert not harness.transport.sent_messages


async def test_free_text_without_dialog_is_explained(harness: BotHarness) -> None:
    await harness.deliver(message_created("привет"))
    assert harness.last_text == texts.UNKNOWN_INPUT


VALID_INN = "7707083893"


def _payload_prefix(harness: BotHarness, prefix: str) -> str:
    for button in harness.buttons():
        if str(button.payload).startswith(prefix):
            return str(button.payload)
    raise AssertionError(f"кнопка {prefix!r} не найдена")


async def _register_provider(harness: BotHarness) -> None:
    await _open_registration(harness, "new_provider")
    await harness.deliver(message_created("Мастер Плюс"))
    await harness.deliver(message_created("+79991112233"))


async def _fill_profile(harness: BotHarness) -> None:
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_KIND_SPECIALIST)))
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_FORM_SELF_EMPLOYED)))
    await harness.deliver(message_created(VALID_INN))
    await harness.deliver(message_callback(_payload_prefix(harness, "d:categories:cat_")))
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_DONE)))
    await harness.deliver(message_callback(_payload_prefix(harness, "d:pcity:city_")))
    if texts.SETUP_WHOLE_CITY in {b.text for b in harness.buttons()}:
        await harness.deliver(message_callback(harness.payload_of(texts.SETUP_WHOLE_CITY)))


async def test_provider_registration_reaches_review_in_bot(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _register_provider(harness)
    assert harness.last_text == texts.SETUP_ASK_KIND
    await _fill_profile(harness)
    assert harness.last_text == texts.SETUP_ASK_CONFIRM
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_SUBMIT)))

    assert texts.SETUP_SUBMITTED in harness.texts
    org = (await db_session.execute(select(Organization))).scalar_one()
    await db_session.refresh(org)
    assert org.inn_normalized == VALID_INN
    assert org.legal_form == "self_employed"
    profile = (await db_session.execute(select(ProviderProfile))).scalar_one()
    await db_session.refresh(profile)
    assert profile.status == "pending_review"
    assert profile.provider_kind == "independent_specialist"
    assert (await db_session.execute(select(ProviderCategory))).scalars().all()
    assert (await db_session.execute(select(ProviderServiceArea))).scalars().all()


async def test_invalid_inn_is_asked_again(harness: BotHarness, db_session: AsyncSession) -> None:
    await _register_provider(harness)
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_KIND_COMPANY)))
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_FORM_OOO)))
    await harness.deliver(message_created("1234567890"))
    assert harness.last_text != texts.SETUP_ASK_CATEGORIES
    conversation = (await db_session.execute(select(BotConversation))).scalar_one()
    await db_session.refresh(conversation)
    assert conversation.current_step == "provider_setup:inn"


async def test_categories_required_before_territory(harness: BotHarness) -> None:
    await _register_provider(harness)
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_KIND_COMPANY)))
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_FORM_OOO)))
    await harness.deliver(message_created(VALID_INN))
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_DONE)))
    assert harness.last_text == texts.SETUP_CATEGORIES_REQUIRED


async def test_draft_is_resumed_from_profile(harness: BotHarness, db_session: AsyncSession) -> None:
    await _register_provider(harness)
    await _fill_profile(harness)
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_SAVE_DRAFT)))
    assert texts.SETUP_SAVED_DRAFT in harness.texts
    profile = (await db_session.execute(select(ProviderProfile))).scalar_one()
    await db_session.refresh(profile)
    assert profile.status == "draft"

    await harness.deliver(message_callback("m:profile"))
    await harness.deliver(message_callback(harness.payload_of(texts.BUTTON_PROFILE_SETUP)))
    assert harness.last_text == texts.SETUP_ASK_KIND
    await _fill_profile(harness)
    await harness.deliver(message_callback(harness.payload_of(texts.SETUP_SUBMIT)))
    await db_session.refresh(profile)
    assert profile.status == "pending_review"

    await harness.deliver(message_callback("m:profile"))
    assert texts.BUTTON_PROFILE_SETUP not in {b.text for b in harness.buttons()}
