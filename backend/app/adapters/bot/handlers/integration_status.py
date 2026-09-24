from __future__ import annotations

from app.adapters.bot import formatting, keyboards, menu, texts
from app.adapters.bot.context import BotContext
from app.core.errors import Forbidden
from app.db.enums import DeliveryState, IntegrationClientStatus, WebhookSubscriptionStatus
from app.modules.integration import api as integration

RECENT_DELIVERIES = 50
SHOWN_ERRORS = 3
_ERROR_STATES = frozenset({DeliveryState.FAILED, DeliveryState.BLOCKED, DeliveryState.RETRYING})


@menu.menu("integration")
async def show_integration(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    settings = [keyboards.rows([keyboards.open_app(texts.INTEGRATION_SETUP, "integration")])]
    if actor is None or actor.side != "provider":
        await ctx.reply(texts.NOT_PROVIDER_SIDE)
        return
    try:
        access = integration.webhook_access(actor)
    except Forbidden:
        await ctx.reply(texts.INTEGRATION_ADMIN_ONLY)
        return

    keys = [
        k
        for k in await integration.list_api_keys(actor)
        if k.status == IntegrationClientStatus.ACTIVE
    ]
    subscriptions = [
        s
        for s in await integration.list_subscriptions(actor)
        if s.status == WebhookSubscriptionStatus.ACTIVE
    ]
    deliveries = await integration.list_deliveries(access.organization_id, limit=RECENT_DELIVERIES)
    errors = [d for d in deliveries.items if d.state in _ERROR_STATES][:SHOWN_ERRORS]

    connected = bool(keys) or bool(subscriptions)
    lines = [
        texts.INTEGRATION_CONNECTED if connected else texts.INTEGRATION_NOT_CONNECTED,
        texts.INTEGRATION_KEYS.format(count=len(keys)),
        texts.INTEGRATION_SUBSCRIPTIONS.format(count=len(subscriptions)),
    ]
    last_used = max((k.last_used_at for k in keys if k.last_used_at), default=None)
    if last_used is not None:
        lines.append(
            texts.INTEGRATION_LAST_USED.format(when=formatting.format_local_moment(last_used, None))
        )
    if errors:
        lines.append(texts.INTEGRATION_ERRORS_TITLE)
        for delivery in errors:
            detail = delivery.last_error or (
                f"HTTP {delivery.last_http_status}" if delivery.last_http_status else "—"
            )
            when = delivery.last_attempt_at or delivery.created_at
            lines.append(
                texts.INTEGRATION_ERROR_ITEM.format(
                    event=delivery.event_type,
                    state=texts.DELIVERY_STATE_LABELS.get(delivery.state, delivery.state),
                    detail=detail[:120],
                    when=formatting.format_local_moment(when, None),
                )
            )
    elif connected:
        lines.append(texts.INTEGRATION_NO_ERRORS)
    await ctx.reply("\n".join(lines), settings)
