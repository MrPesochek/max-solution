import uuid
from datetime import datetime

import structlog
from sqlalchemy import delete, update

from app.core import ids
from app.core.actor import Actor
from app.core.clock import utcnow
from app.core.errors import NotFound
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db import session as db_session
from app.db.models import IdempotencyKey, WebhookSubscription
from app.infra.config import get_settings
from app.modules.integration import policy, transport
from app.modules.integration.keys import secret_box
from app.modules.integration.views import SCHEMA_VERSION, EventEnvelopeView, WebhookTestResultView

log = structlog.get_logger(__name__)


def build_ping_envelope(
    *, organization_id: uuid.UUID, event_id: uuid.UUID, event_type: str, now: datetime
) -> EventEnvelopeView:
    return EventEnvelopeView(
        schema_version=SCHEMA_VERSION,
        event_id=ids.encode("event", event_id),
        type=event_type,
        occurred_at=now,
        recipient_organization_id=ids.encode("organization", organization_id),
        resource_id=ids.encode("webhook_subscription", event_id),
        resource_version=None,
        data={"test": True},
    )


async def send_test(
    actor: Actor,
    subscription_public_id: str,
    *,
    event_type: str | None = None,
    idem: Idempotency | None = None,
) -> WebhookTestResultView:
    access = policy.webhook_access(actor)
    subscription_id = ids.decode("webhook_subscription", subscription_public_id)
    kind = event_type or policy.PING_EVENT_TYPE
    if kind != policy.PING_EVENT_TYPE:
        kind = policy.check_event_types([kind])[0]

    settings = get_settings()
    now = utcnow()
    event_id = uuid.uuid4()
    delivery_id = uuid.uuid4()
    target: dict[str, str] = {}

    async def claim(ctx: CommandContext) -> CommandResult:
        subscription = await ctx.session.get(WebhookSubscription, subscription_id)
        if subscription is None or not policy.owns_subscription(access, subscription):
            raise NotFound()
        target["url"] = subscription.url
        target["secret"] = secret_box().decrypt(subscription.secret_encrypted).decode()
        pending = WebhookTestResultView(
            delivered=False,
            event_id=ids.encode("event", event_id),
            delivery_id=ids.encode("delivery", delivery_id),
            error="in_progress",
        )
        return CommandResult(pending.model_dump(mode="json"))

    claimed = await run_command(actor, claim, idempotency=idem)
    if claimed.replayed:
        return WebhookTestResultView.model_validate(claimed.body)

    envelope = build_ping_envelope(
        organization_id=access.organization_id, event_id=event_id, event_type=kind, now=now
    )
    outgoing = transport.OutgoingWebhook(
        url=target["url"],
        secret=target["secret"],
        event_id=envelope.event_id,
        delivery_id=ids.encode("delivery", delivery_id),
        body=transport.build_body(envelope),
        timestamp=int(now.timestamp()),
    )
    try:
        result = await transport.deliver(
            outgoing,
            timeout=settings.webhook_timeout_seconds,
            private_hosts=settings.private_webhook_hosts,
        )
    except BaseException:
        if idem is not None:
            await _release_key(actor, idem)
        raise
    log.info(
        "webhook_test_sent",
        subscription_id=subscription_public_id,
        outcome=result.outcome,
        status=result.status_code,
    )
    view = WebhookTestResultView(
        delivered=result.delivered,
        event_id=outgoing.event_id,
        delivery_id=outgoing.delivery_id,
        status_code=result.status_code,
        error=result.error,
    )
    if idem is not None:
        async with db_session.transaction() as session:
            await session.execute(
                update(IdempotencyKey)
                .where(
                    IdempotencyKey.scope == actor.idempotency_scope,
                    IdempotencyKey.key == idem.key,
                )
                .values(response_body=view.model_dump(mode="json"))
            )
    return view


async def _release_key(actor: Actor, idem: Idempotency) -> None:
    try:
        async with db_session.transaction() as session:
            await session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.scope == actor.idempotency_scope,
                    IdempotencyKey.key == idem.key,
                    IdempotencyKey.response_body["error"].astext == "in_progress",
                )
            )
    except Exception:
        log.exception("webhook_test_key_release_failed")
