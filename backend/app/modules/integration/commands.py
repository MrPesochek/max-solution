import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import structlog
from sqlalchemy import select, update

from app.core import ids
from app.core.actor import Actor
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db.enums import (
    DeliveryState,
    IntegrationClientStatus,
    MembershipRole,
    MembershipStatus,
    WebhookSubscriptionStatus,
)
from app.db.models import (
    IntegrationClient,
    IntegrationEvent,
    Membership,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import get_settings
from app.infra.crypto import generate_token
from app.infra.net.ssrf import SsrfValidationError, validate_webhook_url
from app.modules.integration import policy
from app.modules.integration.keys import issue_api_key, secret_box
from app.modules.integration.views import (
    to_api_key_issued_view,
    to_api_key_view,
    to_delivery_view,
    to_subscription_secret_view,
    to_subscription_view,
)

log = structlog.get_logger(__name__)

MAX_URL_LENGTH = 2000


@dataclass(slots=True)
class ApiKeyCreateData:
    name: str
    scopes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SubscriptionCreateData:
    url: str
    events: list[str] = field(default_factory=list)
    client_public_id: str | None = None


def _check_url(url: str) -> str:
    value = url.strip()
    if not value or len(value) > MAX_URL_LENGTH:
        raise ValidationFailed("Укажите корректный URL вебхука", field="url")
    try:
        validate_webhook_url(value, private_hosts=get_settings().private_webhook_hosts)
    except SsrfValidationError as exc:
        raise ValidationFailed(
            "URL вебхука недопустим", code="WEBHOOK_URL_REJECTED", field="url", reason=exc.reason
        ) from exc
    return value


async def _notify_org_admins(
    ctx: CommandContext,
    organization_id: uuid.UUID,
    notification_type: str,
    payload: dict[str, str],
) -> None:
    rows = (
        await ctx.session.execute(
            select(Membership.id, Membership.user_id).where(
                Membership.organization_id == organization_id,
                Membership.role == MembershipRole.PROVIDER_ADMIN,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).all()
    for membership_id, user_id in rows:
        ctx.notify(
            user_id,
            notification_type,
            payload,
            membership_id=membership_id,
            organization_id=organization_id,
        )


async def _ensure_provider_may_change(ctx: CommandContext, organization_id: uuid.UUID) -> None:
    from app.modules.requests import api as requests_api

    await requests_api.ensure_provider_not_suspended(ctx.session, organization_id)


async def create_api_key(
    actor: Actor, data: ApiKeyCreateData, *, idem: Idempotency | None
) -> CommandResult:
    admin = policy.require_provider_admin(actor)
    scopes = policy.check_scopes(data.scopes)
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Укажите название ключа", field="name")
    issued = issue_api_key()

    async def handler(ctx: CommandContext) -> CommandResult:
        await _ensure_provider_may_change(ctx, admin.organization_id)
        client = IntegrationClient(
            provider_org_id=admin.organization_id,
            name=name,
            api_key_hash=issued.digest,
            api_key_prefix=issued.prefix,
            scopes=scopes,
            status=IntegrationClientStatus.ACTIVE.value,
            created_by_membership_id=admin.membership_id,
        )
        ctx.session.add(client)
        await ctx.session.flush()
        ctx.audit(
            "integration.api_key.create",
            "integration_client",
            client.id,
            organization_id=admin.organization_id,
            scopes=scopes,
        )
        await _notify_org_admins(
            ctx,
            admin.organization_id,
            "integration.api_key.created",
            {"client_id": ids.encode("integration_client", client.id), "name": name},
        )
        view = to_api_key_issued_view(client, issued.raw)
        return CommandResult(view.model_dump(mode="json"), status=201, secret_fields=("key",))

    return await run_command(actor, handler, idempotency=idem)


async def _own_client(
    ctx: CommandContext, organization_id: uuid.UUID, client_id: uuid.UUID
) -> IntegrationClient:
    client = await lock_by_id(ctx.session, IntegrationClient, client_id)
    if client.provider_org_id != organization_id:
        raise NotFound()
    return client


async def revoke_api_key(
    actor: Actor, client_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    admin = policy.require_provider_admin(actor)
    client_id = ids.decode("integration_client", client_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        client = await _own_client(ctx, admin.organization_id, client_id)
        if client.status != IntegrationClientStatus.ACTIVE:
            raise Conflict("Ключ уже отозван", code="API_KEY_REVOKED")
        client.status = IntegrationClientStatus.REVOKED.value
        client.revoked_at = ctx.now
        disabled = (
            (
                await ctx.session.execute(
                    update(WebhookSubscription)
                    .where(
                        WebhookSubscription.integration_client_id == client.id,
                        WebhookSubscription.status == WebhookSubscriptionStatus.ACTIVE.value,
                    )
                    .values(status=WebhookSubscriptionStatus.DISABLED.value, disabled_at=ctx.now)
                    .returning(WebhookSubscription.id)
                )
            )
            .scalars()
            .all()
        )
        ctx.audit(
            "integration.api_key.revoke",
            "integration_client",
            client.id,
            organization_id=admin.organization_id,
            disabled_subscriptions=len(disabled),
        )
        await _notify_org_admins(
            ctx,
            admin.organization_id,
            "integration.api_key.revoked",
            {"client_id": client_public_id, "name": client.name},
        )
        return CommandResult(to_api_key_view(client).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def rotate_api_key(
    actor: Actor, client_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    admin = policy.require_provider_admin(actor)
    client_id = ids.decode("integration_client", client_public_id)
    issued = issue_api_key()

    async def handler(ctx: CommandContext) -> CommandResult:
        client = await _own_client(ctx, admin.organization_id, client_id)
        if client.status != IntegrationClientStatus.ACTIVE:
            raise Conflict("Ключ отозван", code="API_KEY_REVOKED")
        await _ensure_provider_may_change(ctx, admin.organization_id)
        client.api_key_hash = issued.digest
        client.api_key_prefix = issued.prefix
        client.rotated_at = ctx.now
        ctx.audit(
            "integration.api_key.rotate",
            "integration_client",
            client.id,
            organization_id=admin.organization_id,
        )
        await _notify_org_admins(
            ctx,
            admin.organization_id,
            "integration.api_key.rotated",
            {"client_id": client_public_id, "name": client.name},
        )
        view = to_api_key_issued_view(client, issued.raw)
        return CommandResult(view.model_dump(mode="json"), secret_fields=("key",))

    return await run_command(actor, handler, idempotency=idem)


async def _resolve_client_id(
    ctx: CommandContext, access: policy.WebhookAccess, client_public_id: str | None
) -> uuid.UUID:
    if access.integration_client_id is not None:
        return access.integration_client_id
    stmt = select(IntegrationClient).where(
        IntegrationClient.provider_org_id == access.organization_id,
        IntegrationClient.status == IntegrationClientStatus.ACTIVE.value,
    )
    if client_public_id is not None:
        stmt = stmt.where(
            IntegrationClient.id == ids.decode("integration_client", client_public_id)
        )
    clients = list((await ctx.session.execute(stmt.limit(2))).scalars())
    if client_public_id is not None and not clients:
        raise NotFound()
    if not clients:
        raise Conflict("Сначала выпустите ключ интеграции", code="NO_ACTIVE_API_KEY")
    if len(clients) > 1:
        raise ValidationFailed("Укажите ключ интеграции", field="client_id")
    return clients[0].id


async def create_subscription(
    actor: Actor, data: SubscriptionCreateData, *, idem: Idempotency | None
) -> CommandResult:
    access = policy.webhook_access(actor)
    url = _check_url(data.url)
    events = policy.check_event_types(data.events)
    secret = generate_token()

    async def handler(ctx: CommandContext) -> CommandResult:
        await _ensure_provider_may_change(ctx, access.organization_id)
        client_id = await _resolve_client_id(ctx, access, data.client_public_id)
        subscription = WebhookSubscription(
            integration_client_id=client_id,
            provider_org_id=access.organization_id,
            url=url,
            event_types=events,
            secret_encrypted=secret_box().encrypt(secret.encode()),
            status=WebhookSubscriptionStatus.ACTIVE.value,
            created_by_membership_id=access.membership_id,
        )
        ctx.session.add(subscription)
        await ctx.session.flush()
        ctx.audit(
            "integration.webhook_subscription.create",
            "webhook_subscription",
            subscription.id,
            organization_id=access.organization_id,
            events=events,
        )
        await _notify_org_admins(
            ctx,
            access.organization_id,
            "integration.webhook.changed",
            {
                "subscription_id": ids.encode("webhook_subscription", subscription.id),
                "change": "created",
            },
        )
        view = to_subscription_secret_view(subscription, secret)
        return CommandResult(view.model_dump(mode="json"), status=201, secret_fields=("secret",))

    return await run_command(actor, handler, idempotency=idem)


async def _own_subscription(
    ctx: CommandContext, access: policy.WebhookAccess, subscription_id: uuid.UUID
) -> WebhookSubscription:
    subscription = await lock_by_id(ctx.session, WebhookSubscription, subscription_id)
    if not policy.owns_subscription(access, subscription):
        raise NotFound()
    return subscription


async def delete_subscription(
    actor: Actor, subscription_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    access = policy.webhook_access(actor)
    subscription_id = ids.decode("webhook_subscription", subscription_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        subscription = await _own_subscription(ctx, access, subscription_id)
        if subscription.status != WebhookSubscriptionStatus.ACTIVE:
            raise Conflict("Подписка уже отключена", code="SUBSCRIPTION_DISABLED")
        subscription.status = WebhookSubscriptionStatus.DISABLED.value
        subscription.disabled_at = ctx.now
        ctx.audit(
            "integration.webhook_subscription.delete",
            "webhook_subscription",
            subscription.id,
            organization_id=access.organization_id,
        )
        await _notify_org_admins(
            ctx,
            access.organization_id,
            "integration.webhook.changed",
            {"subscription_id": subscription_public_id, "change": "disabled"},
        )
        return CommandResult(to_subscription_view(subscription).model_dump(mode="json"), status=200)

    return await run_command(actor, handler, idempotency=idem)


async def enable_subscription(
    actor: Actor, subscription_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    access = policy.webhook_access(actor)
    subscription_id = ids.decode("webhook_subscription", subscription_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        subscription = await _own_subscription(ctx, access, subscription_id)
        if subscription.status == WebhookSubscriptionStatus.ACTIVE:
            raise Conflict("Подписка уже включена", code="SUBSCRIPTION_ACTIVE")
        await _ensure_provider_may_change(ctx, access.organization_id)
        client = await ctx.session.get(IntegrationClient, subscription.integration_client_id)
        if client is None or client.status != IntegrationClientStatus.ACTIVE:
            raise Conflict("Ключ подписки отозван", code="API_KEY_REVOKED")
        _check_url(subscription.url)
        subscription.status = WebhookSubscriptionStatus.ACTIVE.value
        subscription.disabled_at = None
        ctx.audit(
            "integration.webhook_subscription.enable",
            "webhook_subscription",
            subscription.id,
            organization_id=access.organization_id,
        )
        await _notify_org_admins(
            ctx,
            access.organization_id,
            "integration.webhook.changed",
            {"subscription_id": subscription_public_id, "change": "enabled"},
        )
        await ctx.session.flush()
        return CommandResult(to_subscription_view(subscription).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def rotate_subscription_secret(
    actor: Actor, subscription_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    access = policy.webhook_access(actor)
    subscription_id = ids.decode("webhook_subscription", subscription_public_id)
    secret = generate_token()

    async def handler(ctx: CommandContext) -> CommandResult:
        subscription = await _own_subscription(ctx, access, subscription_id)
        await _ensure_provider_may_change(ctx, access.organization_id)
        subscription.secret_encrypted = secret_box().encrypt(secret.encode())
        ctx.audit(
            "integration.webhook_subscription.rotate_secret",
            "webhook_subscription",
            subscription.id,
            organization_id=access.organization_id,
        )
        await _notify_org_admins(
            ctx,
            access.organization_id,
            "integration.webhook.changed",
            {"subscription_id": subscription_public_id, "change": "secret_rotated"},
        )
        view = to_subscription_secret_view(subscription, secret)
        return CommandResult(view.model_dump(mode="json"), secret_fields=("secret",))

    return await run_command(actor, handler, idempotency=idem)


async def redeliver(
    actor: Actor, delivery_public_id: str, *, idem: Idempotency | None = None
) -> CommandResult:
    access = policy.delivery_access(actor)
    delivery_id = ids.decode("delivery", delivery_public_id)
    window = timedelta(seconds=get_settings().webhook_retry_window_seconds)

    async def handler(ctx: CommandContext) -> CommandResult:
        delivery = await lock_by_id(ctx.session, WebhookDelivery, delivery_id)
        if access is not None and delivery.provider_org_id != access.organization_id:
            raise NotFound()
        if access is not None:
            await _ensure_provider_may_change(ctx, access.organization_id)
        if delivery.state == DeliveryState.QUEUED:
            raise Conflict("Доставка уже в очереди", code="DELIVERY_QUEUED")
        if delivery.lease_until is not None and delivery.lease_until > ctx.now:
            raise Conflict("Доставка сейчас отправляется", code="DELIVERY_IN_FLIGHT")
        delivery.state = DeliveryState.QUEUED.value
        delivery.next_attempt_at = ctx.now
        delivery.lease_until = None
        delivery.expires_at = ctx.now + window
        delivery.last_error = None
        ctx.audit(
            "integration.webhook_delivery.redeliver",
            "webhook_delivery",
            delivery.id,
            organization_id=delivery.provider_org_id,
        )
        event_type = await ctx.session.scalar(
            select(IntegrationEvent.event_type).where(
                IntegrationEvent.id == delivery.integration_event_id
            )
        )
        view = to_delivery_view(delivery, event_type or "", ctx.now)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)
