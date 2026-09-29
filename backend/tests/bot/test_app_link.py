from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import runtime as bot_runtime
from app.adapters.bot import texts
from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Unauthenticated
from app.db.models import User
from app.infra.config import Settings
from app.infra.max.types import ButtonOpenApp
from app.modules.identity import api as identity
from app.worker import notification_templates as templates
from tests import factories
from tests.bot.conftest import (
    USER_ID,
    WEBHOOK_SECRET,
    BotHarness,
    build_harness,
    message_callback,
    message_created,
)

OTHER_USER_ID = 78
LINK_PREFIX = "https://example.test/#/auth/link?t="


@pytest.fixture
def link_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(
        monkeypatch,
        MAX_UPDATES_MODE="webhook",
        MAX_WEBHOOK_SECRET=WEBHOOK_SECRET,
        PUBLIC_BASE_URL="https://example.test",
        MAX_WEBAPP_MODE="link",
    )


@pytest.fixture
def link_harness(link_settings: Settings, clean_db: None) -> Iterator[BotHarness]:
    built = build_harness()
    bot_runtime.set_runtime(built.runtime)
    try:
        yield built
    finally:
        bot_runtime.set_runtime(None)


async def _manager(db: AsyncSession, max_user_id: int = USER_ID) -> User:
    user = await factories.create_user(db, max_user_id=str(max_user_id), display_name="Иван")
    org = await factories.create_organization(db, name="ООО Ромашка")
    await factories.create_membership(db, user, org, role="customer_manager")
    await db.commit()
    return user


def _login_url(harness: BotHarness) -> str:
    sent = harness.transport.sent_messages[-1]
    [button] = harness.buttons()
    assert button.type == "link"
    assert str(button.url).startswith(LINK_PREFIX)
    assert sent.user_id is not None and sent.chat_id is None
    return str(button.url)


async def test_open_app_button_sends_fresh_login_link(
    link_harness: BotHarness, db_session: AsyncSession
) -> None:
    await _manager(db_session)
    await link_harness.deliver(message_created("/start"))
    payload = link_harness.payload_of(texts.OPEN_WEBAPP)
    assert payload == "o:scr_home"
    link_harness.reset()

    await link_harness.deliver(message_callback(payload))

    assert link_harness.transport.answered_callbacks
    assert link_harness.transport.sent_messages[-1].user_id == USER_ID
    url = _login_url(link_harness)
    assert link_harness.buttons()[0].text == texts.LOGIN_LINK_BUTTON
    result = await identity.login_with_link(url.removeprefix(LINK_PREFIX))
    assert result.target == "scr_home"
    assert result.issued.user.display_name == "Иван"


async def test_each_press_gives_new_single_use_link(
    link_harness: BotHarness, db_session: AsyncSession
) -> None:
    await _manager(db_session)
    await link_harness.deliver(message_callback("o:scr_equipment"))
    first = _login_url(link_harness)
    await link_harness.deliver(message_callback("o:scr_equipment"))
    second = _login_url(link_harness)

    assert first != second
    await identity.login_with_link(first.removeprefix(LINK_PREFIX))
    with pytest.raises(Unauthenticated):
        await identity.login_with_link(first.removeprefix(LINK_PREFIX))


async def test_mini_app_mode_keeps_open_app_button(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await _manager(db_session)

    await harness.deliver(message_created("/start"))

    [button] = [b for b in harness.buttons() if b.text == texts.OPEN_WEBAPP]
    assert isinstance(button, ButtonOpenApp)
    assert button.payload == "scr_home"


async def _notification_button(db: AsyncSession, user: User) -> tuple[str, str]:
    request_public_id = ids.encode("request", user.id)
    message = await templates.render(
        db,
        "request.submitted",
        {"request_id": request_public_id},
        recipient_user_id=user.id,
        now=utcnow(),
    )
    await db.commit()
    [attachment] = message.attachments or []
    [[button]] = attachment.payload.buttons  # type: ignore[union-attr]
    return str(button.payload), request_public_id


async def test_notification_button_is_bound_to_recipient(
    link_harness: BotHarness, db_session: AsyncSession
) -> None:
    user = await _manager(db_session)
    payload, request_public_id = await _notification_button(db_session, user)
    assert payload.startswith("a:")
    assert request_public_id not in payload

    await link_harness.deliver(message_callback(payload))
    first = _login_url(link_harness)
    await link_harness.deliver(message_callback(payload))
    second = _login_url(link_harness)

    assert first != second
    result = await identity.login_with_link(second.removeprefix(LINK_PREFIX))
    assert result.target == f"req_{request_public_id}"


async def test_forwarded_notification_button_does_not_log_in_other_user(
    link_harness: BotHarness, db_session: AsyncSession
) -> None:
    user = await _manager(db_session)
    await _manager(db_session, OTHER_USER_ID)
    payload, _ = await _notification_button(db_session, user)
    link_harness.reset()

    await link_harness.deliver(message_callback(payload, user_id=OTHER_USER_ID))

    assert link_harness.transport.answered_callbacks[-1].notification == texts.ACTION_OUTDATED
    for index in range(len(link_harness.transport.sent_messages)):
        assert all(
            not str(getattr(b, "url", "")).startswith(LINK_PREFIX)
            for b in link_harness.buttons(index)
        )


async def test_notification_in_mini_app_mode_keeps_open_app_button(
    bot_settings: Settings, db_session: AsyncSession
) -> None:
    user = await _manager(db_session)
    payload, request_public_id = await _notification_button(db_session, user)
    assert payload == f"req_{request_public_id}"
