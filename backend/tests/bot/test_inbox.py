from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from maxapi.methods.types.getted_updates import process_update_webhook
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import menu, texts, updates
from app.core.clock import utcnow
from app.db.models import BotConversation, MaxUpdate, Membership, Organization
from app.infra.config import get_settings
from app.infra.max.transport import MaxApiError, MaxRetryableError
from app.modules.identity import api as identity
from tests.bot.conftest import (
    BotHarness,
    contact_message,
    message_callback,
    message_created,
)


async def _city_payload(harness: BotHarness) -> str:
    for button in harness.buttons():
        payload = str(button.payload)
        if payload.startswith("d:city:city_"):
            return payload
    raise AssertionError("кнопка города не найдена")


async def _registration_until_address(harness: BotHarness) -> None:
    """Регистрация заказчика до последнего шага: остаётся прислать адрес."""
    await harness.deliver(message_created("/start"))
    await harness.deliver(message_callback("m:new_customer"))
    await harness.deliver(message_created("ООО Ромашка"))
    await harness.deliver(contact_message("+79990000000"))
    await harness.deliver(message_callback(await _city_payload(harness)))
    district = next(
        (str(b.payload) for b in harness.buttons() if str(b.payload).startswith("d:district:dst_")),
        None,
    )
    if district is not None:
        await harness.deliver(message_callback(district))
    harness.reset()


def _fail_once(monkeypatch: pytest.MonkeyPatch, target: Any, name: str) -> Callable[[], int]:
    """Первый вызов падает временной ошибкой, следующие идут в настоящую функцию."""
    original: Callable[..., Awaitable[Any]] = getattr(target, name)
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("временный сбой")
        return await original(*args, **kwargs)

    monkeypatch.setattr(target, name, flaky)
    return lambda: calls["n"]


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _row(session: AsyncSession) -> MaxUpdate:
    session.expire_all()
    rows = (await session.execute(select(MaxUpdate).order_by(MaxUpdate.received_at))).scalars()
    return list(rows)[-1]


async def test_retry_after_failure_before_command_runs_it_once(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой до команды: повтор того же события от MAX выполняет её, и ровно один раз."""
    await _registration_until_address(harness)
    calls = _fail_once(monkeypatch, identity, "create_organization")
    event = message_created("ул. Тестовая, 1")

    first = await harness.deliver(event)
    assert first.failed is True
    assert await _count(db_session, Organization) == 0
    row = await _row(db_session)
    assert row.status == "failed"
    assert row.attempts == 1
    assert row.next_retry_at is not None

    second = await harness.deliver(event)

    assert second.duplicate is False
    assert second.failed is False
    assert calls() == 2
    assert await _count(db_session, Organization) == 1
    assert await _count(db_session, Membership) == 1
    row = await _row(db_session)
    assert row.status == "processed"
    assert row.raw_payload == {}
    assert row.conversation_snapshot is None


async def test_retry_after_failure_after_command_does_not_repeat_it(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой после команды: повтор не создаёт второй объект и не дублирует ответы."""
    await _registration_until_address(harness)
    _fail_once(monkeypatch, menu, "send_menu")
    event = message_created("ул. Тестовая, 1")

    first = await harness.deliver(event)
    assert first.failed is True
    assert await _count(db_session, Organization) == 1
    created_text = texts.ORG_CREATED_CUSTOMER.format(name="ООО Ромашка")
    assert harness.texts.count(created_text) == 1

    second = await harness.deliver(event)

    assert second.failed is False
    assert await _count(db_session, Organization) == 1
    assert await _count(db_session, Membership) == 1
    assert harness.texts.count(created_text) == 1
    assert any(str(b.payload).startswith("m:") for b in harness.buttons())


async def test_processed_event_is_duplicate(harness: BotHarness, db_session: AsyncSession) -> None:
    event = message_created("/help")
    assert (await harness.deliver(event)).duplicate is False
    sent = len(harness.transport.sent_messages)
    assert (await harness.deliver(event)).duplicate is True
    assert len(harness.transport.sent_messages) == sent


async def test_event_in_live_lease_is_not_taken_twice(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Событие в обработке у другого экземпляра: повтор от MAX его не перехватывает."""
    event_json = message_created("/help")
    event = await process_update_webhook(event_json=event_json, bot=harness.runtime.bot)
    assert event is not None
    await updates.record(event)
    assert await updates.acquire(updates.update_key(event), utcnow()) is not None

    outcome = await harness.deliver(event_json)

    assert outcome.duplicate is True
    assert not harness.transport.sent_messages


async def test_crash_between_record_and_handling_is_recovered(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Процесс упал после фиксации события: worker доводит обработку сам."""
    from app.worker import max_updates_recovery

    await _registration_until_address(harness)
    event = await process_update_webhook(
        event_json=message_created("ул. Тестовая, 1"), bot=harness.runtime.bot
    )
    assert event is not None
    await updates.record(event)

    assert await max_updates_recovery.run_once(utcnow()) == 0
    assert await _count(db_session, Organization) == 0

    later = utcnow() + timedelta(minutes=10)
    assert await max_updates_recovery.run_once(later) == 1

    assert await _count(db_session, Organization) == 1
    row = await _row(db_session)
    assert row.status == "processed"
    assert row.attempts == 1


async def test_expired_lease_is_recovered_without_repeating_effects(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обработчик «умер» посреди работы: аренда истекла, повтор не дублирует ответы."""
    from app.worker import max_updates_recovery

    await _registration_until_address(harness)
    event_json = message_created("ул. Тестовая, 1")
    event = await process_update_webhook(event_json=event_json, bot=harness.runtime.bot)
    assert event is not None

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit("процесс остановлен")

    monkeypatch.setattr(menu, "send_menu", crash)
    with pytest.raises(SystemExit):
        await updates.process(harness.runtime.dispatcher, event)
    monkeypatch.undo()

    row = await _row(db_session)
    assert row.status == "processing"
    assert await _count(db_session, Organization) == 1
    created_text = texts.ORG_CREATED_CUSTOMER.format(name="ООО Ромашка")
    assert harness.texts.count(created_text) == 1

    later = utcnow() + timedelta(minutes=10)
    assert await max_updates_recovery.run_once(later) == 1

    assert await _count(db_session, Organization) == 1
    assert harness.texts.count(created_text) == 1
    row = await _row(db_session)
    assert row.status == "processed"
    assert row.attempts == 2


async def test_failed_event_is_retried_by_worker_when_due(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import max_updates_recovery

    await _registration_until_address(harness)
    _fail_once(monkeypatch, identity, "create_organization")
    await harness.deliver(message_created("ул. Тестовая, 1"))
    row = await _row(db_session)
    assert row.status == "failed"
    assert row.next_retry_at is not None

    assert await max_updates_recovery.run_once(row.next_retry_at - timedelta(seconds=1)) == 0
    assert await max_updates_recovery.run_once(row.next_retry_at) == 1

    assert await _count(db_session, Organization) == 1
    assert (await _row(db_session)).status == "processed"


async def test_exhausted_attempts_move_event_to_dead(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import max_updates_recovery

    monkeypatch.setenv("MAX_UPDATE_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("постоянный сбой")

    monkeypatch.setattr(menu, "send_menu", boom)
    event = message_created("/start")
    await harness.deliver(event)
    assert (await _row(db_session)).status == "failed"

    for _ in range(5):
        row = await _row(db_session)
        if row.status != "failed":
            break
        assert row.next_retry_at is not None
        await max_updates_recovery.run_once(row.next_retry_at)

    row = await _row(db_session)
    assert row.status == "dead"
    assert row.attempts == 3
    assert row.processing_error == "RuntimeError"
    assert row.next_retry_at is None
    assert await max_updates_recovery.run_once(utcnow() + timedelta(days=1)) == 0
    assert (await harness.deliver(event)).duplicate is True
    assert (await _row(db_session)).attempts == 3


async def test_stuck_last_attempt_is_buried(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Последняя попытка зависла (процесс упал) — событие уходит в dead, а не висит."""
    from app.worker import max_updates_recovery

    event = await process_update_webhook(
        event_json=message_created("/help"), bot=harness.runtime.bot
    )
    assert event is not None
    await updates.record(event)
    await db_session.execute(
        sql_update(MaxUpdate).values(
            status="processing",
            attempts=get_settings().max_update_max_attempts,
            lease_until=utcnow() - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    await max_updates_recovery.run_once(utcnow())

    row = await _row(db_session)
    assert row.status == "dead"
    assert row.processing_error == "lease_expired"
    assert not harness.transport.sent_messages


async def test_group_event_without_payload_is_buried(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Групповое событие не хранится целиком — повторить его нечем, оно уходит в dead."""
    from app.worker import max_updates_recovery

    event = await process_update_webhook(
        event_json={
            "update_type": "bot_added",
            "timestamp": 1_700_000_000_000,
            "chat_id": 900,
            "user": {"user_id": 5, "first_name": "А", "is_bot": False, "last_activity_time": 1},
            "is_channel": False,
        },
        bot=harness.runtime.bot,
    )
    assert event is not None
    await updates.record(event)

    assert await max_updates_recovery.run_once(utcnow() + timedelta(minutes=10)) == 1

    row = await _row(db_session)
    assert row.raw_payload == {}
    assert row.status == "dead"
    assert row.processing_error == "no_payload"


async def test_polling_middleware_retries_failed_event(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Polling идёт через тот же inbox: повтор после сбоя выполняет действие один раз."""
    await _registration_until_address(harness)
    harness.runtime.dispatcher.register_outer_middleware(updates.DedupMiddleware())
    calls = _fail_once(monkeypatch, identity, "create_organization")
    event = await process_update_webhook(
        event_json=message_created("ул. Тестовая, 1"), bot=harness.runtime.bot
    )
    assert event is not None

    await harness.runtime.dispatcher.handle(event)
    assert (await _row(db_session)).status == "failed"
    await harness.runtime.dispatcher.handle(event)
    await harness.runtime.dispatcher.handle(event)

    assert calls() == 2
    assert await _count(db_session, Organization) == 1
    assert (await _row(db_session)).status == "processed"


async def test_button_consumed_by_crashed_attempt_is_reclaimed_by_its_replay(
    db_session: AsyncSession,
) -> None:
    """Кнопку погасила попытка, которая не дожила до команды: её повтор гасит снова,
    а любое другое нажатие получает «уже использована»."""
    from app.adapters.bot import actions, conversations
    from app.db import session as app_session
    from tests import factories

    user = await factories.create_user(db_session)
    await db_session.commit()
    now = utcnow()
    async with app_session.transaction() as session:
        code = await actions.make_action(session, user.id, "test.action", now)

    async def claim(key: str | None) -> object:
        token = conversations.current_update.set(key)
        try:
            async with app_session.transaction() as session:
                return await actions.claim(session, code, user.id, now)
        finally:
            conversations.current_update.reset(token)

    first = await claim("message_callback:cb-1")
    assert isinstance(first, actions.ClaimedAction)
    assert actions.CONSUMED_BY_PARAM not in first.params

    replay = await claim("message_callback:cb-1")
    assert isinstance(replay, actions.ClaimedAction)
    assert replay.idempotency == first.idempotency

    other = await claim("message_callback:cb-2")
    assert isinstance(other, actions.RejectedAction)
    assert other.reason == actions.ActionRejection.CONSUMED
    outside = await claim(None)
    assert isinstance(outside, actions.RejectedAction)


def test_event_idempotency_is_stable_across_attempts() -> None:
    def keys(number: int) -> list[str | None]:
        attempt = updates.Attempt(
            key="message_created:mid-1", number=number, previous_replies=[], snapshot=None
        )
        token = updates._attempt.set(attempt)
        try:
            found = [
                updates.event_idempotency("requests.update_draft", {"a": 1}),
                updates.event_idempotency("requests.update_draft", {"a": 2}),
                updates.event_idempotency("files.upload_attachment", {}),
            ]
        finally:
            updates._attempt.reset(token)
        return [idem.key if idem is not None else None for idem in found]

    first, second = keys(1), keys(2)
    assert first == second
    assert len(set(first)) == 3
    assert updates.event_idempotency("requests.update_draft", {}) is None


async def _dialog(session: AsyncSession) -> BotConversation:
    session.expire_all()
    return (await session.execute(select(BotConversation))).scalar_one()


async def test_stale_event_does_not_leak_into_restarted_dialog(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Регистрацию отменили и начали заново: повтор старого адреса в неё не попадает."""
    await _registration_until_address(harness)
    calls = _fail_once(monkeypatch, identity, "create_organization")
    stale = message_created("ул. Старая, 1")
    assert (await harness.deliver(stale)).failed is True

    await harness.deliver(message_created("/cancel"))
    await harness.deliver(message_callback("m:new_customer"))
    before = await _dialog(db_session)
    step, data = before.current_step, dict(before.context.get("data") or {})
    harness.reset()

    outcome = await harness.deliver(stale)

    assert outcome.failed is False
    assert outcome.duplicate is False
    assert calls() == 1
    assert harness.texts == []
    assert await _count(db_session, Organization) == 0
    after = await _dialog(db_session)
    assert after.current_step == step
    assert dict(after.context.get("data") or {}) == data
    key = f"message_created:{stale['message']['body']['mid']}"
    row = (
        await db_session.execute(select(MaxUpdate).where(MaxUpdate.max_update_id == key))
    ).scalar_one()
    assert row.status == "processed"
    assert row.processing_error == updates.SUPERSEDED
    assert row.raw_payload == {}

    await harness.deliver(message_created("ООО Новая"))
    assert "ул. Старая" not in str((await _dialog(db_session)).context)
    assert (await harness.deliver(stale)).duplicate is True


async def test_stale_event_is_not_replayed_by_worker(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """То же через восстановление в worker: устаревшее событие закрывается без действия."""
    await _registration_until_address(harness)
    _fail_once(monkeypatch, identity, "create_organization")
    assert (await harness.deliver(message_created("ул. Старая, 1"))).failed is True
    await harness.deliver(message_created("/start"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.reset()
    await db_session.execute(
        sql_update(MaxUpdate)
        .where(MaxUpdate.status == "failed")
        .values(next_retry_at=utcnow() - timedelta(seconds=1))
    )
    await db_session.commit()

    from app.worker import max_updates_recovery

    assert await max_updates_recovery.run_once(utcnow()) == 1

    assert await _count(db_session, Organization) == 0
    assert harness.texts == []
    assert "ул. Старая" not in str((await _dialog(db_session)).context)


async def test_temporary_send_failure_keeps_event_for_retry(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Единичный 429 на вопрос следующего шага: событие повторяется, вопрос доходит."""
    await harness.deliver(message_created("/start"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.reset()
    harness.transport.send_message_failures.append(
        MaxRetryableError(429, "too_many_requests", "слишком часто")
    )
    event = message_created("ООО Ромашка")

    first = await harness.deliver(event)

    assert first.failed is True
    row = await _row(db_session)
    assert row.status == "failed"
    assert row.processing_error == "ReplyNotDelivered"
    assert row.next_retry_at is not None
    question = harness.last_text
    attempts_to_send = len(harness.transport.sent_messages)
    harness.reset()

    second = await harness.deliver(event)

    assert second.failed is False
    assert harness.texts.count(question) == 1
    assert len(harness.transport.sent_messages) == attempts_to_send
    assert (await _row(db_session)).status == "processed"
    await harness.deliver(contact_message("+79990000000"))
    assert (await _dialog(db_session)).context["data"].get("name") == "ООО Ромашка"


async def test_delivered_replies_are_not_repeated_around_failed_one(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Из трёх ответов не дошёл средний: повтор досылает только его."""
    await _registration_until_address(harness)
    sent: list[str] = []
    original = harness.transport.send_message

    async def second_fails(**kwargs: Any) -> str:
        sent.append(str(kwargs.get("text")))
        if len(sent) == 2:
            raise MaxRetryableError(503, "connection_error", "нет связи")
        return await original(**kwargs)

    monkeypatch.setattr(harness.transport, "send_message", second_fails)
    event = message_created("ул. Тестовая, 1")

    assert (await harness.deliver(event)).failed is True
    delivered_first = list(harness.texts)
    lost = sent[1]
    assert lost not in delivered_first
    monkeypatch.setattr(harness.transport, "send_message", original)
    harness.reset()

    assert (await harness.deliver(event)).failed is False

    assert harness.texts == [lost]
    assert await _count(db_session, Organization) == 1


async def test_permanent_send_failure_does_not_retry_event(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """Пользователь заблокировал бота (403): повторять нечего, событие обработано."""
    await harness.deliver(message_created("/start"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.transport.send_message_failures.append(
        MaxApiError(403, "forbidden", "бот заблокирован")
    )

    outcome = await harness.deliver(message_created("ООО Ромашка"))

    assert outcome.failed is False
    assert (await _row(db_session)).status == "processed"


async def test_crash_before_snapshot_does_not_replay_into_new_dialog(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Процесс упал до записи снимка диалога: worker не отдаёт старый адрес новой регистрации."""
    await _registration_until_address(harness)
    stale = message_created("ул. Старая, 1")
    key = f"message_created:{stale['message']['body']['mid']}"

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, "bind_conversation", crash)
    with pytest.raises(SystemExit):
        await harness.deliver(stale)
    monkeypatch.undo()
    row = (
        await db_session.execute(select(MaxUpdate).where(MaxUpdate.max_update_id == key))
    ).scalar_one()
    assert row.status == "processing" and row.conversation_snapshot is None

    await harness.deliver(message_created("/cancel"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.reset()
    from app.worker import max_updates_recovery

    later = utcnow() + timedelta(seconds=get_settings().max_update_lease_seconds + 1)
    assert await max_updates_recovery.run_once(later) == 1

    assert harness.texts == []
    assert await _count(db_session, Organization) == 0
    assert "ул. Старая" not in str((await _dialog(db_session)).context)
    db_session.expire_all()
    row = (
        await db_session.execute(select(MaxUpdate).where(MaxUpdate.max_update_id == key))
    ).scalar_one()
    assert row.status == "processed" and row.processing_error == updates.SUPERSEDED


async def test_crash_before_snapshot_in_untouched_dialog_is_replayed(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же обрыв, но диалог никто не трогал: worker доводит событие как обычно."""
    await _registration_until_address(harness)
    event = message_created("ул. Тестовая, 1")

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, "bind_conversation", crash)
    with pytest.raises(SystemExit):
        await harness.deliver(event)
    monkeypatch.undo()
    harness.reset()
    from app.worker import max_updates_recovery

    later = utcnow() + timedelta(seconds=get_settings().max_update_lease_seconds + 1)
    assert await max_updates_recovery.run_once(later) == 1

    assert await _count(db_session, Organization) == 1
    assert (await _row(db_session)).status == "processed"


async def test_crash_between_record_and_acquire_does_not_replay_into_new_dialog(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обрыв между фиксацией и арендой: попытка №1 от worker тоже не путает диалоги."""
    await _registration_until_address(harness)
    stale = message_created("ул. Старая, 1")
    key = f"message_created:{stale['message']['body']['mid']}"

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, "acquire", crash)
    with pytest.raises(SystemExit):
        await harness.deliver(stale)
    monkeypatch.undo()
    row = (
        await db_session.execute(select(MaxUpdate).where(MaxUpdate.max_update_id == key))
    ).scalar_one()
    assert row.status == "received" and row.attempts == 0

    await harness.deliver(message_created("/cancel"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.reset()
    from app.worker import max_updates_recovery

    later = utcnow() + timedelta(seconds=get_settings().max_update_lease_seconds + 1)
    assert await max_updates_recovery.run_once(later) == 1

    assert harness.texts == []
    assert await _count(db_session, Organization) == 0
    assert "ул. Старая" not in str((await _dialog(db_session)).context)
    db_session.expire_all()
    row = (
        await db_session.execute(select(MaxUpdate).where(MaxUpdate.max_update_id == key))
    ).scalar_one()
    assert row.status == "processed" and row.processing_error == updates.SUPERSEDED


async def test_redelivery_of_unhandled_event_after_dialog_moved_is_superseded(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же обрыв, но событие повторно приносит сам MAX, а не worker."""
    await _registration_until_address(harness)
    stale = message_created("ул. Старая, 1")

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, "acquire", crash)
    with pytest.raises(SystemExit):
        await harness.deliver(stale)
    monkeypatch.undo()
    await harness.deliver(message_created("/cancel"))
    await harness.deliver(message_callback("m:new_customer"))
    harness.reset()

    outcome = await harness.deliver(stale)

    assert outcome.failed is False and outcome.duplicate is False
    assert harness.texts == []
    assert await _count(db_session, Organization) == 0
    assert "ул. Старая" not in str((await _dialog(db_session)).context)


async def test_redelivery_of_unhandled_event_in_untouched_dialog_is_handled(
    harness: BotHarness, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обрыв до аренды, диалог не трогали: повтор от MAX выполняет действие."""
    await _registration_until_address(harness)
    event = message_created("ул. Тестовая, 1")

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, "acquire", crash)
    with pytest.raises(SystemExit):
        await harness.deliver(event)
    monkeypatch.undo()

    assert (await harness.deliver(event)).failed is False
    assert await _count(db_session, Organization) == 1


@pytest.mark.parametrize("crash_point", ["acquire", "bind_conversation"])
async def test_first_start_is_recovered_after_crash(
    harness: BotHarness,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
) -> None:
    """Первый /start нового пользователя: обрыв до обработки, worker создаёт диалог сам.

    Только что созданная строка диалога не считается чужим изменением — приветствие
    доходит, событие обработано.
    """
    start = message_created("/start")

    async def crash(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(updates, crash_point, crash)
    with pytest.raises(SystemExit):
        await harness.deliver(start)
    monkeypatch.undo()
    if crash_point == "acquire":
        assert await _count(db_session, BotConversation) == 0
    else:
        assert "update" not in (await _dialog(db_session)).context
    harness.reset()
    from app.worker import max_updates_recovery

    later = utcnow() + timedelta(seconds=get_settings().max_update_lease_seconds + 1)
    assert await max_updates_recovery.run_once(later) == 1

    assert harness.texts, "приветствие не отправлено"
    assert any(str(b.payload).startswith("m:") for b in harness.buttons())
    row = await _row(db_session)
    assert row.status == "processed" and row.processing_error is None
