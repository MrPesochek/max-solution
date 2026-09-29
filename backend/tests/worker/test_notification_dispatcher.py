from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.models import Notification, User
from app.infra.max.transport import FakeMaxTransport, MaxApiError, MaxRetryableError
from app.worker import notification_dispatcher, notification_templates
from tests import factories

pytestmark = pytest.mark.asyncio


async def _recipient(session: AsyncSession, *, bot_available: bool = True) -> User:
    user = await factories.create_user(session, max_user_id="770001")
    user.bot_available = bot_available
    await session.flush()
    return user


async def _reload(session: AsyncSession) -> list[Notification]:
    stmt = select(Notification).execution_options(populate_existing=True).order_by(Notification.id)
    return list((await session.execute(stmt)).scalars())


async def test_sends_rendered_message(db_session: AsyncSession) -> None:
    user = await _recipient(db_session)
    await factories.create_notification(
        db_session, user, notification_type="request.assigned", payload={"request_id": "req_1"}
    )
    await db_session.commit()

    transport = FakeMaxTransport()
    assert await notification_dispatcher.run_once(utcnow(), transport=transport) == 1

    assert len(transport.sent_messages) == 1
    call = transport.sent_messages[0]
    assert call.user_id == 770001
    assert call.text == "Новая заявка на ремонт: нужен ответ исполнителя"
    assert call.attachments

    notification = (await _reload(db_session))[0]
    assert notification.state == "sent"
    assert notification.sent_at is not None
    assert notification.last_error is None


async def test_unknown_type_falls_back_to_generic_text(db_session: AsyncSession) -> None:
    user = await _recipient(db_session)
    await factories.create_notification(db_session, user, notification_type="something.new")
    await db_session.commit()

    transport = FakeMaxTransport()
    await notification_dispatcher.run_once(utcnow(), transport=transport)

    assert transport.sent_messages[0].text == notification_templates.FALLBACK_TEXT
    assert (await _reload(db_session))[0].state == "sent"


async def test_bot_unavailable_is_skipped(db_session: AsyncSession) -> None:
    user = await _recipient(db_session, bot_available=False)
    await factories.create_notification(db_session, user)
    await db_session.commit()

    transport = FakeMaxTransport()
    assert await notification_dispatcher.run_once(utcnow(), transport=transport) == 0
    assert transport.sent_messages == []

    notification = (await _reload(db_session))[0]
    assert notification.state == "skipped"
    assert notification.last_error == "bot_unavailable"


async def test_retryable_error_is_retried_then_failed(db_session: AsyncSession) -> None:
    user = await _recipient(db_session)
    await factories.create_notification(db_session, user)
    await db_session.commit()

    transport = FakeMaxTransport()
    transport.send_message_failures.append(MaxRetryableError(503, "unavailable", "MAX недоступен"))
    await notification_dispatcher.run_once(utcnow(), transport=transport)

    notification = (await _reload(db_session))[0]
    assert notification.state == "queued"
    assert notification.attempt_count == 1
    assert notification.last_error == "max_retryable:503"
    assert notification.next_attempt_at is not None and notification.next_attempt_at > utcnow()

    notification.attempt_count = 5
    notification.next_attempt_at = utcnow()
    await db_session.commit()

    transport.send_message_failures.append(MaxRetryableError(503, "unavailable", "MAX недоступен"))
    await notification_dispatcher.run_once(utcnow(), transport=transport)
    assert (await _reload(db_session))[0].state == "failed"


async def test_permanent_error_fails_without_message_text(db_session: AsyncSession) -> None:
    user = await _recipient(db_session)
    await factories.create_notification(db_session, user)
    await db_session.commit()

    transport = FakeMaxTransport()
    transport.send_message_failures.append(MaxApiError(400, "bad_request", "нельзя писать"))
    await notification_dispatcher.run_once(utcnow(), transport=transport)

    notification = (await _reload(db_session))[0]
    assert notification.state == "failed"
    assert notification.last_error == "max_error:MaxApiError"
    assert "нельзя писать" not in (notification.last_error or "")


async def test_non_numeric_max_user_id_is_not_sent(db_session: AsyncSession) -> None:
    user = await factories.create_user(db_session, max_user_id="demo:alice")
    user.bot_available = True
    await factories.create_notification(db_session, user)
    await db_session.commit()

    transport = FakeMaxTransport()
    await notification_dispatcher.run_once(utcnow(), transport=transport)
    assert transport.sent_messages == []
    assert (await _reload(db_session))[0].last_error == "max_user_id_invalid"


async def test_sent_notification_is_not_taken_twice(db_session: AsyncSession) -> None:
    user = await _recipient(db_session)
    await factories.create_notification(db_session, user)
    await db_session.commit()

    transport = FakeMaxTransport()
    await notification_dispatcher.run_once(utcnow(), transport=transport)
    assert await notification_dispatcher.run_once(utcnow(), transport=transport) == 0
    assert len(transport.sent_messages) == 1


async def test_stale_lease_is_released(db_session: AsyncSession) -> None:
    """Зависший экземпляр (взял в аренду, не записал результат) не держит задание вечно."""
    user = await _recipient(db_session)
    await factories.create_notification(db_session, user)
    await db_session.commit()

    leased = await notification_dispatcher.lease(utcnow())
    assert len(leased) == 1
    assert await notification_dispatcher.lease(utcnow()) == []

    notification = (await _reload(db_session))[0]
    assert notification.state == "queued"
    notification.lease_until = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    transport = FakeMaxTransport()
    assert await notification_dispatcher.run_once(utcnow(), transport=transport) == 1
    assert (await _reload(db_session))[0].state == "sent"
