from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.adapters.bot import keyboards, texts
from app.core.actor import CUSTOMER_ROLES
from app.infra.max.types import Button
from app.modules.identity import api as identity

if TYPE_CHECKING:
    from app.adapters.bot.context import BotContext


def side_of(membership: identity.MembershipView) -> str:
    return "customer" if membership.role in CUSTOMER_ROLES else "provider"


def side_title(membership: identity.MembershipView) -> str:
    return texts.ORG_KIND_CUSTOMER if side_of(membership) == "customer" else texts.ORG_KIND_PROVIDER


NEW_CUSTOMER = "new_customer"
NEW_PROVIDER = "new_provider"
SWITCH_ORG = "switch_org"
MAIN = "main"
ORGANIZATION = "organization"


@dataclass(frozen=True, slots=True)
class MenuItem:
    key: str
    title: str
    screen: str


CUSTOMER_ITEMS: tuple[MenuItem, ...] = (
    MenuItem("my_service", "Мой сервис", "my_service"),
    MenuItem("find_provider", "Найти исполнителя", "find_provider"),
    MenuItem("my_requests", "Мои заявки", "requests"),
    MenuItem("equipment", "Оборудование", "equipment"),
    MenuItem(ORGANIZATION, "Организация", "organization"),
)

PROVIDER_ITEMS: tuple[MenuItem, ...] = (
    MenuItem("inbox", "Входящие", "inbox"),
    MenuItem("available", "Доступные заявки", "available"),
    MenuItem("in_progress", "В работе", "in_progress"),
    MenuItem("profile", "Профиль", "profile"),
    MenuItem(ORGANIZATION, "Организация", "organization"),
    MenuItem("integration", "Интеграция", "integration"),
)

MenuHandler = Callable[["BotContext"], Awaitable[None]]

_HANDLERS: dict[str, MenuHandler] = {}


def menu(key: str) -> Callable[[MenuHandler], MenuHandler]:
    """Регистрирует обработчик пункта меню."""

    def decorator(fn: MenuHandler) -> MenuHandler:
        _HANDLERS[key] = fn
        return fn

    return decorator


def handler_for(key: str) -> MenuHandler | None:
    return _HANDLERS.get(key)


def items_for(side: str) -> tuple[MenuItem, ...]:
    return PROVIDER_ITEMS if side == "provider" else CUSTOMER_ITEMS


def find(key: str) -> MenuItem | None:
    return next((i for i in CUSTOMER_ITEMS + PROVIDER_ITEMS if i.key == key), None)


def _chunked(buttons: list[Button], size: int = 2) -> list[list[Button]]:
    return [buttons[i : i + size] for i in range(0, len(buttons), size)]


async def send_menu(ctx: BotContext, *, greeting: str | None = None) -> None:
    """Главное меню. Активная организация всегда видна в заголовке (ТЗ 3)."""
    memberships = await ctx.memberships()
    active = await ctx.active_membership()
    await ctx.save()

    if not memberships:
        await ctx.reply(
            greeting or texts.GREETING_NEW,
            [
                keyboards.rows(
                    [
                        keyboards.menu_button(texts.CREATE_CUSTOMER, NEW_CUSTOMER),
                        keyboards.menu_button(texts.CREATE_PROVIDER, NEW_PROVIDER),
                    ]
                )
            ],
        )
        return

    if active is None:
        await send_organization_choice(ctx, memberships)
        return

    buttons = [keyboards.menu_button(item.title, item.key) for item in items_for(side_of(active))]
    rows = _chunked(buttons)
    tail: list[Button] = [keyboards.open_app(texts.OPEN_WEBAPP, "home")]
    if len([m for m in memberships if m.status == "active"]) > 1:
        tail.append(keyboards.menu_button(texts.CHANGE_ORG, SWITCH_ORG))
    rows.append(tail)

    header = "\n".join(
        (
            texts.MENU_HEADER.format(name=active.organization.name),
            texts.MENU_SIDE.format(side=side_title(active)),
        )
    )
    text = f"{greeting}\n\n{header}" if greeting else f"{header}\n{texts.MENU_PROMPT}"
    await ctx.reply(text, [keyboards.rows(*rows)])


async def send_organization_choice(
    ctx: BotContext, memberships: list[identity.MembershipView] | None = None
) -> None:
    items = memberships if memberships is not None else await ctx.memberships()
    active = [m for m in items if m.status == "active"]
    if not active:
        await ctx.reply(texts.MEMBERSHIP_PENDING)
        return
    buttons = [
        keyboards.select_org_button(f"{m.organization.name} · {side_title(m)}", m.id)
        for m in active
    ]
    await ctx.reply(texts.CHOOSE_ORG, [keyboards.rows(*_chunked(buttons, 1))])
