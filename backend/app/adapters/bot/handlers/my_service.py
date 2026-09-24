from __future__ import annotations

from app.adapters.bot import menu
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import requests_shared
from app.db.enums import RequestRoute


@menu.menu("my_service")
async def show_my_service(ctx: BotContext) -> None:
    await requests_shared.open_collection(ctx, route=RequestRoute.OWN_SERVICE)
