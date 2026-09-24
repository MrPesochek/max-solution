from __future__ import annotations

from app.adapters.bot import menu
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import requests_shared
from app.db.enums import RequestRoute


@menu.menu("find_provider")
async def show_find_provider(ctx: BotContext) -> None:
    await requests_shared.open_collection(ctx, route=RequestRoute.MARKETPLACE)
