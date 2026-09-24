from __future__ import annotations

import uuid

from app.adapters.bot import actions, buttons, conditions, formatting, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.core import ids
from app.core.actor import UserActor
from app.infra.max.types import Button
from app.modules.requests import api as requests_api

PAGE_SIZE = 8

ACTION_OPEN_CARD = "requests.open_card"
ACTION_SWITCH_TAB = "requests.switch_tab"
ACTION_MORE = "requests.more"


@menu.menu("my_requests")
async def show_my_requests(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    await _send_list(ctx, active=True, page=0)


async def _send_list(ctx: BotContext, *, active: bool, page: int) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    items, _ = await requests_api.list_requests(actor, active=active, limit=100)
    chunk, has_prev, has_next = keyboards.paginate(items, page, PAGE_SIZE)

    specs: list[list[ActionSpec]] = [
        [
            ActionSpec(
                texts.REQUEST_LIST_ITEM.format(
                    number=item.request_number,
                    status=texts.STATUS_LABELS.get(item.status, item.status),
                    title=item.equipment_title or "оборудование",
                ),
                ACTION_OPEN_CARD,
                object_type="request",
                object_id=ids.decode("request", item.id),
            )
        ]
        for item in chunk
    ]
    nav: list[ActionSpec] = []
    if has_prev:
        nav.append(
            ActionSpec(texts.BUTTON_PREV, ACTION_MORE, params={"active": active, "page": page - 1})
        )
    if has_next:
        nav.append(
            ActionSpec(texts.BUTTON_MORE, ACTION_MORE, params={"active": active, "page": page + 1})
        )
    specs.append(nav)
    other_tab = texts.REQUESTS_TAB_DONE if active else texts.REQUESTS_TAB_ACTIVE
    specs.append([ActionSpec(other_tab, ACTION_SWITCH_TAB, params={"active": not active})])
    rows = await buttons.mint_rows(ctx, specs)
    rows.append([keyboards.menu_button(texts.BUTTON_TO_MENU, menu.MAIN)])

    title = texts.REQUESTS_TAB_ACTIVE if active else texts.REQUESTS_TAB_DONE
    text = f"{title}\n{texts.REQUESTS_EMPTY}" if not items else title
    await ctx.reply(text, [keyboards.rows(*rows)])


@actions.action(ACTION_MORE)
async def _more(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _send_list(
        ctx,
        active=bool(claimed.params.get("active", True)),
        page=int(claimed.params.get("page", 0)),
    )


@actions.action(ACTION_SWITCH_TAB)
async def _switch_tab(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _send_list(ctx, active=bool(claimed.params.get("active", True)), page=0)


@actions.action(ACTION_OPEN_CARD)
async def _open_card(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await send_card(ctx, claimed.object_id)


async def send_card(ctx: BotContext, request_id: uuid.UUID) -> None:
    from app.adapters.bot.handlers import cards

    if not await cards.show_request(ctx, request_id):
        await ctx.reply(texts.ACTION_OUTDATED)


async def send_customer_card(
    ctx: BotContext, actor: UserActor, view: requests_api.RequestCustomerView
) -> None:
    from app.adapters.bot.handlers import request_actions

    tz = view.location.timezone
    lines = [
        texts.REQUEST_CARD_HEADER.format(number=view.request_number),
        texts.REQUEST_CARD_STATUS.format(status=texts.STATUS_LABELS.get(view.status, view.status)),
    ]
    waiting = texts.WAITING_FOR.get(view.status)
    if waiting:
        lines.append(texts.REQUEST_CARD_WAITING.format(who=waiting))
    lines.extend(_status_lines(view))

    approved_visit = next((p for p in view.visit_proposals if p.status == "approved"), None)
    if approved_visit is not None:
        window = conditions.window_text(
            approved_visit.visit_window_start, approved_visit.visit_window_end, tz
        )
        lines.append(texts.REQUEST_CARD_VISIT.format(window=window))
    approved_quote = next((q for q in view.repair_quotes if q.status == "approved"), None)
    if approved_quote is not None:
        price = approved_quote.price
        lines.append(
            texts.REQUEST_CARD_QUOTE.format(
                price=conditions.price_text(
                    price.amount_minor, price.currency, price.zero_cost_reason, price.vat_mode
                )
            )
        )

    visit = request_actions.pending_visit(view)
    if visit is not None:
        lines.append("")
        lines.extend(
            conditions.visit_lines(
                number=view.request_number,
                version=visit.version,
                window_start=visit.visit_window_start,
                window_end=visit.visit_window_end,
                amount_minor=visit.price.amount_minor,
                currency=visit.price.currency,
                zero_cost_reason=visit.price.zero_cost_reason,
                vat_mode=visit.price.vat_mode,
                scope=visit.scope_description,
                valid_until=visit.valid_until,
                tz=tz,
            )
        )
    quote = request_actions.pending_quote(view)
    if quote is not None:
        lines.append("")
        lines.extend(
            conditions.quote_lines(
                number=view.request_number,
                version=quote.version,
                description=quote.description_of_work,
                amount_minor=quote.price.amount_minor,
                currency=quote.price.currency,
                zero_cost_reason=quote.price.zero_cost_reason,
                vat_mode=quote.price.vat_mode,
                valid_until=quote.valid_until,
                tz=tz,
            )
        )
    if (visit is not None or quote is not None) and not actor.is_manager:
        lines.append(texts.APPROVAL_BY_MANAGER)

    rows: list[list[Button]] = list(await request_actions.card_buttons(ctx, actor, view))
    rows.append([keyboards.open_app(texts.BUTTON_OPEN_IN_APP, "request", view.id)])
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


def _status_lines(view: requests_api.RequestCustomerView) -> list[str]:
    assignment = view.assignment
    if view.status == "awaiting_provider":
        return [texts.REQUEST_CARD_DELIVERED]
    if view.status == "scheduled":
        return [texts.REQUEST_CARD_SCHEDULED]
    if view.status == "accepted" and assignment is not None:
        return [texts.REQUEST_CARD_ACCEPTED]
    if view.status == "action_required":
        reason = None
        if assignment is not None:
            reason = (
                assignment.decline_reason
                or assignment.withdrawal_reason
                or assignment.revoke_reason
            )
        lines = [texts.REQUEST_CARD_DECISION_NEEDED]
        if reason:
            lines.append(texts.REQUEST_CARD_REASON.format(reason=reason))
        return lines
    if (
        view.status == "awaiting_assignment_confirmation"
        and assignment is not None
        and assignment.expires_at is not None
    ):
        deadline = formatting.format_local_moment(assignment.expires_at, view.location.timezone)
        return [texts.REQUEST_CARD_WAITING_UNTIL.format(deadline=deadline)]
    return []
