from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import structlog
from maxapi.enums.chat_type import ChatType
from maxapi.enums.update import UpdateType
from maxapi.types.updates import UpdateUnion
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.updates.message_edited import MessageEdited
from maxapi.types.users import User as MaxUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import conversations
from app.adapters.bot.conversations import ConversationState
from app.core import ids
from app.core.actor import Actor, UserActor
from app.core.clock import utcnow
from app.core.scope import AccessScope, scope_of
from app.db import session as db_session
from app.infra.max.transport import MaxApiError, MaxTransport
from app.infra.max.types import OutgoingAttachment, TextFormat
from app.modules.identity import api as identity

log = structlog.get_logger("bot")

DEFAULT_NAME = "Пользователь MAX"


def sender_of(event: UpdateUnion) -> MaxUser | None:
    if isinstance(event, MessageCreated | MessageEdited):
        return event.message.sender
    if isinstance(event, MessageCallback):
        return event.callback.user
    user = getattr(event, "user", None)
    return user if isinstance(user, MaxUser) else None


def chat_id_of(event: UpdateUnion) -> int | None:
    chat_id = getattr(event, "chat_id", None)
    if isinstance(chat_id, int):
        return chat_id
    if isinstance(event, MessageCreated | MessageEdited):
        return event.message.recipient.chat_id
    if isinstance(event, MessageCallback) and event.message is not None:
        return event.message.recipient.chat_id
    return None


_GROUP_UPDATES = frozenset(
    {
        UpdateType.BOT_ADDED,
        UpdateType.BOT_REMOVED,
        UpdateType.USER_ADDED,
        UpdateType.USER_REMOVED,
        UpdateType.CHAT_TITLE_CHANGED,
        UpdateType.MESSAGE_CHAT_CREATED,
    }
)


def is_personal_dialog(event: UpdateUnion) -> bool:
    """Бот работает только в личном диалоге: в группе ответ увидели бы все участники."""
    if event.update_type in _GROUP_UPDATES:
        return False
    if (
        isinstance(event, MessageCreated | MessageEdited | MessageCallback)
        and event.message is not None
    ):
        return event.message.recipient.chat_type == ChatType.DIALOG
    return True


def display_name_of(user: MaxUser) -> str:
    parts = [p for p in (user.first_name, user.last_name) if p]
    if parts:
        return " ".join(parts)
    return user.username or DEFAULT_NAME


@dataclass(slots=True)
class BotContext:
    event: UpdateUnion
    transport: MaxTransport
    now: datetime
    max_user_id: int
    chat_id: int | None
    display_name: str
    user_id: uuid.UUID
    conversation: ConversationState

    @asynccontextmanager
    async def unit(self) -> AsyncIterator[AsyncSession]:
        """Транзакция, которая на выходе сохраняет состояние диалога."""
        async with db_session.transaction() as session:
            yield session
            await conversations.save(session, self.conversation)

    async def save(self) -> None:
        async with self.unit():
            pass

    async def reply(
        self,
        text: str,
        attachments: list[OutgoingAttachment] | None = None,
        *,
        format: TextFormat | None = None,
    ) -> None:
        try:
            if self.chat_id is not None:
                await self.transport.send_message(
                    chat_id=self.chat_id, text=text, attachments=attachments, format=format
                )
            else:
                await self.transport.send_message(
                    user_id=self.max_user_id, text=text, attachments=attachments, format=format
                )
        except MaxApiError as exc:
            log.warning("bot_send_failed", status=exc.status, code=exc.code)

    async def ack(self, notification: str | None = None) -> None:
        if not isinstance(self.event, MessageCallback):
            return
        try:
            await self.transport.answer_callback(
                self.event.callback.callback_id, notification=notification
            )
        except MaxApiError as exc:
            log.warning("bot_answer_failed", status=exc.status, code=exc.code)

    async def memberships(self) -> list[identity.MembershipView]:
        return await identity.list_user_memberships(self.user_id)

    async def active_membership(self) -> identity.MembershipView | None:
        """Активное членство диалога; единственная организация выбирается сама."""
        items = [m for m in await self.memberships() if m.status == "active"]
        if not items:
            if self.conversation.active_organization_id is not None:
                self.conversation.active_organization_id = None
                self.conversation.active_membership_id = None
            return None
        current_membership = self.conversation.active_membership_id
        if current_membership is not None:
            for item in items:
                if ids.decode("membership", item.id) == current_membership:
                    return item
        current = self.conversation.active_organization_id
        if current is not None:
            in_org = [
                item
                for item in items
                if ids.decode("organization", item.organization.id) == current
            ]
            if len(in_org) == 1:
                await self.set_active(in_org[0])
                return in_org[0]
        if len(items) == 1:
            await self.set_active(items[0])
            return items[0]
        self.conversation.active_organization_id = None
        self.conversation.active_membership_id = None
        return None

    async def set_active(self, membership: identity.MembershipView) -> None:
        self.conversation.active_organization_id = ids.decode(
            "organization", membership.organization.id
        )
        self.conversation.active_membership_id = ids.decode("membership", membership.id)

    async def actor(self) -> Actor:
        membership = await self.active_membership()
        if membership is None:
            return await identity.actor_for_user(self.user_id, None)
        return await identity.actor_for_user(
            self.user_id,
            ids.decode("organization", membership.organization.id),
            ids.decode("membership", membership.id),
        )

    async def org_actor(self) -> UserActor | None:
        actor = await self.actor()
        return actor if isinstance(actor, UserActor) else None

    async def scope(self) -> AccessScope | None:
        actor = await self.org_actor()
        return scope_of(actor) if actor is not None else None


async def build_context(
    event: UpdateUnion, transport: MaxTransport, *, available: bool | None = True
) -> BotContext | None:
    """Готовит контекст: отмечает доступность бота (D32) и поднимает диалог из БД."""
    sender = sender_of(event)
    if sender is None or sender.is_bot:
        return None

    now = utcnow()
    chat_id = chat_id_of(event)
    max_user_id = str(sender.user_id)
    display_name = display_name_of(sender)
    started = event.update_type == UpdateType.BOT_STARTED

    async with db_session.transaction() as session:
        user = await conversations.touch_user(
            session, max_user_id, display_name, now, started=started, available=available
        )
        conversation = await conversations.load_or_create(
            session, user.id, str(chat_id) if chat_id is not None else f"u{sender.user_id}"
        )
        user_id = user.id

    return BotContext(
        event=event,
        transport=transport,
        now=now,
        max_user_id=sender.user_id,
        chat_id=chat_id,
        display_name=display_name,
        user_id=user_id,
        conversation=conversation,
    )
