import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select

from app.core import ids
from app.core.actor import Actor, IntegrationActor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound
from app.db import session as db_session
from app.db.enums import DeliveryState, IntegrationClientStatus, WebhookSubscriptionStatus
from app.db.models import (
    IntegrationClient,
    IntegrationEvent,
    IntegrationFeedCounter,
    Organization,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import get_settings
from app.modules.integration import policy
from app.modules.integration.views import (
    ApiKeyView,
    DeliveryPageView,
    EventsPageView,
    IntegrationDeliveriesStatsView,
    IntegrationSummaryView,
    IntegrationWebhookBriefView,
    WebhookSubscriptionView,
    to_api_key_view,
    to_delivery_view,
    to_envelope,
    to_subscription_view,
)

DEFAULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class IntegrationIdentityView:
    """`GET /me`: организация интеграции и её разрешения (ТЗ 10.2)."""

    organization_id: str
    organization_name: str
    client_id: str
    client_name: str
    key_prefix: str
    scopes: list[str]


class CursorExpired(Conflict):
    code = "CURSOR_EXPIRED"
    default_message = "Курсор ленты событий устарел, выполните сверку через список заявок"


def _events_org(actor: Actor) -> uuid.UUID:
    if isinstance(actor, IntegrationActor):
        if policy.EVENTS_READ not in actor.scopes:
            raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=policy.EVENTS_READ)
        return actor.organization_id
    return policy.require_provider_admin(actor).organization_id


async def describe_actor(actor: IntegrationActor) -> IntegrationIdentityView:
    async with db_session.transaction() as session:
        row = (
            await session.execute(
                select(IntegrationClient, Organization)
                .join(Organization, Organization.id == IntegrationClient.provider_org_id)
                .where(IntegrationClient.id == actor.integration_client_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFound()
        client, org = row
        return IntegrationIdentityView(
            organization_id=ids.encode("organization", org.id),
            organization_name=org.display_name,
            client_id=ids.encode("integration_client", client.id),
            client_name=client.name,
            key_prefix=client.api_key_prefix,
            scopes=sorted(client.scopes),
        )


async def list_api_keys(actor: Actor) -> list[ApiKeyView]:
    """Ключи видит только администратор исполнителя — как и выпускает их (ТЗ 6.7)."""
    admin = policy.require_provider_admin(actor)
    async with db_session.transaction() as session:
        rows = (
            await session.execute(
                select(IntegrationClient)
                .where(IntegrationClient.provider_org_id == admin.organization_id)
                .order_by(IntegrationClient.created_at.desc())
            )
        ).scalars()
        return [to_api_key_view(row) for row in rows]


async def list_subscriptions(actor: Actor) -> list[WebhookSubscriptionView]:
    """Ключ видит только свои подписки, администратор — все подписки организации."""
    access = policy.webhook_access(actor)
    async with db_session.transaction() as session:
        stmt = (
            select(WebhookSubscription)
            .where(WebhookSubscription.provider_org_id == access.organization_id)
            .order_by(WebhookSubscription.created_at.desc())
        )
        if access.integration_client_id is not None:
            stmt = stmt.where(
                WebhookSubscription.integration_client_id == access.integration_client_id
            )
        rows = (await session.execute(stmt)).scalars()
        return [to_subscription_view(row) for row in rows]


async def get_subscription(actor: Actor, subscription_public_id: str) -> WebhookSubscriptionView:
    access = policy.webhook_access(actor)
    subscription_id = ids.decode("webhook_subscription", subscription_public_id)
    async with db_session.transaction() as session:
        subscription = await session.get(WebhookSubscription, subscription_id)
        if subscription is None or not policy.owns_subscription(access, subscription):
            raise NotFound()
        return to_subscription_view(subscription)


def parse_events_cursor(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise CursorExpired() from exc
    if value < 0:
        raise CursorExpired()
    return value


async def list_events(actor: Actor, *, cursor: str | None, limit: int) -> EventsPageView:
    organization_id = _events_org(actor)
    visible_types = (
        policy.readable_event_types(actor.scopes) if isinstance(actor, IntegrationActor) else None
    )
    page_limit = max(1, min(limit, get_settings().events_page_max_limit))
    position = parse_events_cursor(cursor)

    async with db_session.transaction() as session:
        oldest, newest = (
            await session.execute(
                select(
                    func.min(IntegrationEvent.feed_seq), func.max(IntegrationEvent.feed_seq)
                ).where(
                    IntegrationEvent.recipient_org_id == organization_id,
                    IntegrationEvent.feed_seq.is_not(None),
                )
            )
        ).one()
        if position is not None:
            counter = await session.scalar(
                select(IntegrationFeedCounter.last_seq).where(
                    IntegrationFeedCounter.organization_id == organization_id
                )
            )
            last_seq = max(counter or 0, newest or 0)
            if position > last_seq:
                raise CursorExpired()
            first_kept = oldest if oldest is not None else last_seq + 1
            if position + 1 < first_kept:
                raise CursorExpired()

        stmt = (
            select(IntegrationEvent)
            .where(
                IntegrationEvent.recipient_org_id == organization_id,
                IntegrationEvent.feed_seq.is_not(None),
            )
            .order_by(IntegrationEvent.feed_seq)
            .limit(page_limit + 1)
        )
        if position is not None:
            stmt = stmt.where(IntegrationEvent.feed_seq > position)
        if visible_types is not None:
            stmt = stmt.where(IntegrationEvent.event_type.in_(visible_types))
        rows = list((await session.execute(stmt)).scalars())

    has_more = len(rows) > page_limit
    page = rows[:page_limit]
    next_cursor = str(page[-1].feed_seq) if page else cursor
    return EventsPageView(
        events=[to_envelope(row) for row in page],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def list_deliveries(
    organization_id: uuid.UUID, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> DeliveryPageView:
    """Последние доставки с результатами — экран «Интеграция» (A18)."""
    now = utcnow()
    page_limit = max(1, min(limit, 100))
    before = ids.decode("delivery", cursor) if cursor else None
    async with db_session.transaction() as session:
        stmt = (
            select(WebhookDelivery, IntegrationEvent.event_type)
            .join(IntegrationEvent, IntegrationEvent.id == WebhookDelivery.integration_event_id)
            .where(WebhookDelivery.provider_org_id == organization_id)
            .order_by(WebhookDelivery.id.desc())
            .limit(page_limit + 1)
        )
        if before is not None:
            stmt = stmt.where(WebhookDelivery.id < before)
        rows = [(d, t) for d, t in (await session.execute(stmt)).all()]

    has_more = len(rows) > page_limit
    page = rows[:page_limit]
    next_cursor = ids.encode("delivery", page[-1][0].id) if has_more and page else None
    return DeliveryPageView(
        items=[to_delivery_view(delivery, event_type, now) for delivery, event_type in page],
        next_cursor=next_cursor,
        has_more=has_more,
    )


SUMMARY_WINDOW = timedelta(hours=24)


async def integration_summary(actor: Actor) -> IntegrationSummaryView:
    """Только администратор исполнителя; секрет подписки в сводку не попадает."""
    admin = policy.require_provider_admin(actor)
    organization_id = admin.organization_id
    now = utcnow()
    async with db_session.transaction() as session:
        active_keys, last_used = (
            await session.execute(
                select(
                    func.count(IntegrationClient.id), func.max(IntegrationClient.last_used_at)
                ).where(
                    IntegrationClient.provider_org_id == organization_id,
                    IntegrationClient.status == IntegrationClientStatus.ACTIVE.value,
                )
            )
        ).one()
        subscription = (
            await session.execute(
                select(WebhookSubscription)
                .where(WebhookSubscription.provider_org_id == organization_id)
                .order_by(
                    (WebhookSubscription.status == WebhookSubscriptionStatus.ACTIVE.value).desc(),
                    WebhookSubscription.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        last_event_at = await session.scalar(
            select(func.max(IntegrationEvent.occurred_at)).where(
                IntegrationEvent.recipient_org_id == organization_id
            )
        )
        by_state = {
            state: int(count)
            for state, count in (
                await session.execute(
                    select(WebhookDelivery.state, func.count())
                    .where(
                        WebhookDelivery.provider_org_id == organization_id,
                        WebhookDelivery.created_at >= now - SUMMARY_WINDOW,
                    )
                    .group_by(WebhookDelivery.state)
                )
            ).all()
        }
    return IntegrationSummaryView(
        connected=int(active_keys) > 0,
        api_keys_active=int(active_keys),
        last_key_used_at=last_used,
        webhook=(
            IntegrationWebhookBriefView(
                id=ids.encode("webhook_subscription", subscription.id),
                url=subscription.url,
                status=subscription.status,
            )
            if subscription is not None
            else None
        ),
        last_event_at=last_event_at,
        deliveries_24h=IntegrationDeliveriesStatsView(
            total=sum(by_state.values()),
            delivered=by_state.get(DeliveryState.DELIVERED.value, 0),
            failed=by_state.get(DeliveryState.FAILED.value, 0)
            + by_state.get(DeliveryState.BLOCKED.value, 0),
            retrying=by_state.get(DeliveryState.RETRYING.value, 0),
            queued=by_state.get(DeliveryState.QUEUED.value, 0),
        ),
    )
