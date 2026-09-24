from __future__ import annotations

from typing import Any

import structlog
from maxapi import Router
from maxapi.enums.update import UpdateType
from maxapi.filters.command import Command, CommandStart
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.updates import UpdateUnion
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from app.adapters.bot import scenarios, texts, updates  # noqa: F401 — регистрирует сценарии
from app.adapters.bot.context import build_context, chat_id_of, is_personal_dialog
from app.adapters.bot.handlers import (  # noqa: F401 — регистрируют пункты меню и действия
    app_link,
    callbacks,
    commands,
    equipment,
    find_provider,
    integration_status,
    invitation,
    messages,
    my_requests,
    my_service,
    organization,
    profile,
    provider_inbox,
    provider_marketplace,
    provider_report,
    provider_setup,
    provider_visit,
    provider_work,
    publication,
    request_actions,
    request_cancel,
    request_details,
    request_offers,
    request_route,
    requests_shared,
)
from app.infra.max.transport import MaxApiError, MaxTransport

log = structlog.get_logger("bot")


class ContextMiddleware(BaseMiddleware):
    """Готовит `BotContext` до обработчика: пользователь, доступность бота, диалог."""

    def __init__(self, transport: MaxTransport) -> None:
        self._transport = transport

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        if not is_personal_dialog(event_object):
            await self._decline_group(event_object)
            return None
        available = event_object.update_type != UpdateType.BOT_STOPPED
        ctx = await build_context(event_object, self._transport, available=available)
        if ctx is None:
            return None
        if not await updates.bind_conversation(ctx.conversation):
            return None
        data["ctx"] = ctx
        return await handler(event_object, data)

    async def _decline_group(self, event: UpdateUnion) -> None:
        """В группе — короткий ответ без данных; пользователь и диалог не заводятся."""
        try:
            if isinstance(event, MessageCreated):
                sender = event.message.sender
                chat_id = chat_id_of(event)
                if chat_id is not None and sender is not None and not sender.is_bot:
                    await self._transport.send_message(chat_id=chat_id, text=texts.PERSONAL_ONLY)
            elif isinstance(event, MessageCallback):
                await self._transport.answer_callback(
                    event.callback.callback_id, notification=texts.PERSONAL_ONLY
                )
        except MaxApiError as exc:
            log.warning("bot_group_reply_failed", status=exc.status, code=exc.code)


def build_router(transport: MaxTransport) -> Router:
    router = Router("bot")
    router.register_outer_middleware(ContextMiddleware(updates.InboxTransport(transport)))

    router.bot_started()(commands.on_bot_started)
    router.bot_stopped()(commands.on_bot_stopped)
    router.message_created(CommandStart())(commands.cmd_start)
    router.message_created(Command("help"))(commands.cmd_help)
    router.message_created(Command("cancel"))(commands.cmd_cancel)
    router.message_created(Command("menu"))(commands.cmd_menu)
    router.message_created()(commands.on_message)
    router.message_callback()(callbacks.on_callback)
    return router
