import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import ColumnElement, any_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import ids
from app.core.locking import lock_by_id
from app.db import session as db_session
from app.db.enums import DeliveryState, IntegrationClientStatus, WebhookSubscriptionStatus
from app.db.models import (
    IntegrationClient,
    IntegrationEvent,
    IntegrationFeedCounter,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import get_settings
from app.modules.integration import policy, transport
from app.modules.integration.keys import secret_box
from app.modules.integration.views import to_envelope

log = structlog.get_logger(__name__)

FEED_LOCK_KEY = 0x52465F46


@dataclass(frozen=True, slots=True)
class DeliveryJob:
    delivery_row_id: uuid.UUID
    delivery_id: uuid.UUID
    provider_org_id: uuid.UUID
    subscription_id: uuid.UUID
    event_type: str
    attempt: int
    outgoing: transport.OutgoingWebhook


async def assign_feed_seq(now: datetime, *, batch: int | None = None) -> int:
    """Присваивает `feed_seq` событиям без номера, по одному счётчику на получателя.

    Один диспетчер на кластер (`pg_advisory_xact_lock`), поэтому номера идут подряд
    и курсор `/events` не имеет пропусков.

    Порядок нумерации — порядок обнаружения, а не порядок `id`. Транзакция с меньшим
    `id` может зафиксироваться позже соседней, и тогда её событие получит больший
    `feed_seq`. Это осознанный выбор: потребителю по ТЗ 11 (п. 3) события и так
    приходят не по порядку, он сверяет `resource_version`; от курсора ему нужны
    монотонность и беспропускность, и то и другое здесь соблюдается. Альтернатива —
    ждать N секунд перед нумерацией — добавляет задержку первой доставки (NFR 15:
    p95 ≤ 5 с) и всё равно не даёт гарантии при долгой транзакции.
    """
    limit = batch or get_settings().feed_dispatch_batch
    async with db_session.transaction() as session:
        await session.execute(select(func.pg_advisory_xact_lock(FEED_LOCK_KEY)))
        rows = (
            await session.execute(
                select(IntegrationEvent.id, IntegrationEvent.recipient_org_id)
                .where(IntegrationEvent.feed_seq.is_(None))
                .order_by(IntegrationEvent.id)
                .limit(limit)
            )
        ).all()
        if not rows:
            return 0

        per_org: dict[uuid.UUID, list[uuid.UUID]] = {}
        for event_id, org_id in rows:
            per_org.setdefault(org_id, []).append(event_id)

        for org_id, event_ids in per_org.items():
            last = (
                await session.execute(
                    pg_insert(IntegrationFeedCounter)
                    .values(organization_id=org_id, last_seq=len(event_ids))
                    .on_conflict_do_update(
                        index_elements=["organization_id"],
                        set_={"last_seq": IntegrationFeedCounter.last_seq + len(event_ids)},
                    )
                    .returning(IntegrationFeedCounter.last_seq)
                )
            ).scalar_one()
            first = last - len(event_ids) + 1
            for offset, event_id in enumerate(event_ids):
                await session.execute(
                    update(IntegrationEvent)
                    .where(IntegrationEvent.id == event_id)
                    .values(feed_seq=first + offset)
                )
        return len(rows)


async def enqueue_deliveries(now: datetime, *, batch: int | None = None) -> int:
    """Создаёт `webhook_deliveries` для активных подписок получателя.

    Идемпотентность — уникальный индекс «событие × подписка» и `INSERT … ON
    CONFLICT DO NOTHING`: конкурентная постановка безопасна на уровне БД без
    advisory-блокировки, поэтому её здесь больше нет (`NOT EXISTS` в выборке
    остаётся — иначе один и тот же уже поставленный хвост событий перевыбирался
    бы на каждом тике диспетчера).
    """
    settings = get_settings()
    limit = batch or settings.webhook_enqueue_batch
    window = timedelta(seconds=settings.webhook_retry_window_seconds)
    cutoff = now - window

    async with db_session.transaction() as session:
        pairs = (
            await session.execute(
                select(
                    IntegrationEvent.id,
                    IntegrationEvent.recipient_org_id,
                    WebhookSubscription.id,
                )
                .join(
                    WebhookSubscription,
                    (WebhookSubscription.provider_org_id == IntegrationEvent.recipient_org_id)
                    & (WebhookSubscription.status == WebhookSubscriptionStatus.ACTIVE.value)
                    & (IntegrationEvent.event_type == any_(WebhookSubscription.event_types)),
                )
                .join(
                    IntegrationClient,
                    (IntegrationClient.id == WebhookSubscription.integration_client_id)
                    & (IntegrationClient.status == IntegrationClientStatus.ACTIVE.value)
                    & (_required_scope() == any_(IntegrationClient.scopes)),
                )
                .where(
                    IntegrationEvent.feed_seq.is_not(None),
                    IntegrationEvent.created_at >= cutoff,
                    ~select(WebhookDelivery.id)
                    .where(
                        WebhookDelivery.integration_event_id == IntegrationEvent.id,
                        WebhookDelivery.webhook_subscription_id == WebhookSubscription.id,
                    )
                    .exists(),
                )
                .order_by(IntegrationEvent.id)
                .limit(limit)
            )
        ).all()
        if not pairs:
            return 0

        stmt = (
            pg_insert(WebhookDelivery)
            .values(
                [
                    {
                        "integration_event_id": event_id,
                        "webhook_subscription_id": subscription_id,
                        "provider_org_id": org_id,
                        "state": DeliveryState.QUEUED.value,
                        "current_delivery_id": uuid.uuid4(),
                        "attempt_count": 0,
                        "next_attempt_at": now,
                        "expires_at": now + window,
                    }
                    for event_id, org_id, subscription_id in pairs
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["integration_event_id", "webhook_subscription_id"]
            )
            .returning(WebhookDelivery.id)
        )
        inserted = (await session.execute(stmt)).scalars().all()
        return len(inserted)


async def lease_deliveries(now: datetime, *, batch: int | None = None) -> list[DeliveryJob]:
    """Забирает пачку заданий и резервирует их полем `lease_until`.

    Аренда отдельна от `next_attempt_at`: строки не заблокированы на время
    HTTP-запроса, а зависшее задание умершего экземпляра освобождается по
    истечении аренды, а не по сроку следующего планового повтора (A22).
    """
    settings = get_settings()
    limit = batch or settings.webhook_send_batch
    lease = timedelta(seconds=settings.webhook_lease_seconds)
    jobs: list[DeliveryJob] = []

    async with db_session.transaction() as session:
        rows = list(
            (
                await session.execute(
                    select(WebhookDelivery)
                    .where(
                        WebhookDelivery.state.in_(
                            [DeliveryState.QUEUED.value, DeliveryState.RETRYING.value]
                        ),
                        or_(
                            WebhookDelivery.next_attempt_at.is_(None),
                            WebhookDelivery.next_attempt_at <= now,
                        ),
                        or_(
                            WebhookDelivery.lease_until.is_(None),
                            WebhookDelivery.lease_until <= now,
                        ),
                    )
                    .order_by(WebhookDelivery.next_attempt_at.nulls_first())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for delivery in rows:
            if delivery.expires_at <= now:
                _fail(delivery, "retry_window_exhausted")
                continue
            subscription = await session.get(WebhookSubscription, delivery.webhook_subscription_id)
            if subscription is None or subscription.status != WebhookSubscriptionStatus.ACTIVE:
                _fail(delivery, "subscription_disabled")
                continue
            client = await session.get(IntegrationClient, subscription.integration_client_id)
            if client is None or client.status != IntegrationClientStatus.ACTIVE:
                _fail(delivery, "api_key_revoked")
                continue
            event = await session.get(IntegrationEvent, delivery.integration_event_id)
            if event is None:
                _fail(delivery, "event_missing")
                continue
            if not policy.can_read_event(client.scopes, event.event_type):
                _fail(delivery, "scope_missing")
                continue

            delivery.attempt_count += 1
            delivery.current_delivery_id = uuid.uuid4()
            delivery.last_attempt_at = now
            delivery.lease_until = now + lease

            envelope = to_envelope(event)
            jobs.append(
                DeliveryJob(
                    delivery_row_id=delivery.id,
                    delivery_id=delivery.current_delivery_id,
                    provider_org_id=delivery.provider_org_id,
                    subscription_id=subscription.id,
                    event_type=event.event_type,
                    attempt=delivery.attempt_count,
                    outgoing=transport.OutgoingWebhook(
                        url=subscription.url,
                        secret=secret_box().decrypt(subscription.secret_encrypted).decode(),
                        event_id=envelope.event_id,
                        delivery_id=ids.encode("delivery", delivery.current_delivery_id),
                        body=transport.build_body(envelope),
                        timestamp=int(now.timestamp()),
                    ),
                )
            )
    return jobs


async def record_attempt(job: DeliveryJob, result: transport.AttemptResult, now: datetime) -> str:
    settings = get_settings()
    async with db_session.transaction() as session:
        delivery = await lock_by_id(session, WebhookDelivery, job.delivery_row_id)
        if delivery.current_delivery_id != job.delivery_id:
            return delivery.state
        delivery.lease_until = None
        delivery.last_http_status = result.status_code
        delivery.last_error = result.error
        if result.outcome == "delivered":
            delivery.state = DeliveryState.DELIVERED.value
            delivery.next_attempt_at = None
        elif result.outcome == "blocked":
            delivery.state = DeliveryState.BLOCKED.value
            delivery.next_attempt_at = None
        elif result.outcome == "permanent":
            delivery.state = DeliveryState.FAILED.value
            delivery.next_attempt_at = None
        else:
            delay = transport.retry_delay(
                delivery.attempt_count,
                base=settings.webhook_retry_base_seconds,
                maximum=settings.webhook_retry_max_seconds,
            )
            scheduled = now + timedelta(seconds=delay)
            if scheduled >= delivery.expires_at:
                delivery.state = DeliveryState.FAILED.value
                delivery.next_attempt_at = None
                delivery.last_error = result.error or "retry_window_exhausted"
            else:
                delivery.state = DeliveryState.RETRYING.value
                delivery.next_attempt_at = scheduled
        return delivery.state


def _required_scope() -> ColumnElement[str]:
    return case(policy.EVENT_SCOPES, value=IntegrationEvent.event_type)


def _fail(delivery: WebhookDelivery, reason: str) -> None:
    delivery.state = DeliveryState.FAILED.value
    delivery.next_attempt_at = None
    delivery.lease_until = None
    delivery.last_error = reason
