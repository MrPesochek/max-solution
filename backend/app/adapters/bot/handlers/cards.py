from __future__ import annotations

import uuid

from app.adapters.bot import menu
from app.adapters.bot.context import BotContext
from app.core.errors import DomainError
from app.modules.requests import api as requests_api


async def show_request(ctx: BotContext, request_id: uuid.UUID) -> bool:
    from app.adapters.bot.handlers import my_requests, provider_work

    actor = await ctx.org_actor()
    if actor is None:
        return False
    try:
        view = await requests_api.get_request(actor, request_id)
    except DomainError:
        return False
    if isinstance(view, requests_api.RequestCustomerView):
        await my_requests.send_customer_card(ctx, actor, view)
        return True
    if isinstance(view, requests_api.RequestProviderView):
        await provider_work.send_work_card(ctx, view)
        return True
    return False


async def show_actual(ctx: BotContext, request_id: uuid.UUID | None) -> None:
    if request_id is not None and await show_request(ctx, request_id):
        return
    await menu.send_menu(ctx)
