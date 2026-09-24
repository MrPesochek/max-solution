from __future__ import annotations

from app.adapters.bot import actions, buttons, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import provider_setup
from app.core.errors import NotFound
from app.db.enums import MembershipRole, ProviderProfileStatus
from app.infra.max.types import Button
from app.modules.providers import api as providers

ACTION_ACCEPTING = "profile.accepting"
ACTION_SETUP = "profile.setup"
_SETUP_STATUSES = frozenset(
    {ProviderProfileStatus.DRAFT.value, ProviderProfileStatus.NEEDS_INFORMATION.value}
)


@menu.menu("profile")
async def show_profile(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None or actor.side != "provider":
        await ctx.reply(texts.NOT_PROVIDER_SIDE)
        return
    await _send_profile(ctx)


async def _send_profile(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    scope = await ctx.scope()
    assert actor is not None and scope is not None
    edit = keyboards.open_app(texts.PROFILE_EDIT, "profile")
    try:
        profile = await providers.get_own_profile(scope)
    except NotFound:
        await ctx.reply(texts.PROFILE_MISSING, [keyboards.rows([edit])])
        return

    lines = [
        texts.PROFILE_TITLE.format(name=profile.name),
        texts.PROFILE_STATUS.format(
            status=texts.PROFILE_STATUS_LABELS.get(profile.status, profile.status)
        ),
    ]
    if profile.status_reason:
        lines.append(texts.PROFILE_STATUS_REASON.format(reason=profile.status_reason))
    confirmed = [badge.title for badge in profile.verification if badge.confirmed]
    lines.append(
        texts.PROFILE_VERIFICATION.format(
            items=", ".join(confirmed) if confirmed else texts.PROFILE_NOTHING_CONFIRMED
        )
    )
    categories = ", ".join(c.name for c in profile.categories) or "—"
    areas = ", ".join(
        f"{a.city_name} ({a.district_name})" if a.district_name else a.city_name
        for a in profile.service_areas
    )
    lines.append(texts.PROFILE_CATEGORIES.format(categories=categories))
    lines.append(texts.PROFILE_AREAS.format(areas=areas or "—"))
    lines.append(
        texts.PROFILE_ACCEPTING_ON
        if profile.accepting_new_requests
        else texts.PROFILE_ACCEPTING_OFF
    )

    rows: list[list[Button]] = []
    is_admin = actor.role == MembershipRole.PROVIDER_ADMIN
    if is_admin and profile.status == ProviderProfileStatus.ACTIVE:
        turn_on = not profile.accepting_new_requests
        rows = await buttons.mint_rows(
            ctx,
            [
                [
                    ActionSpec(
                        texts.BUTTON_ACCEPTING_ON if turn_on else texts.BUTTON_ACCEPTING_OFF,
                        ACTION_ACCEPTING,
                        params={"accepting": turn_on},
                    )
                ]
            ],
        )
    elif is_admin and profile.status in _SETUP_STATUSES:
        rows = await buttons.mint_rows(
            ctx, [[ActionSpec(texts.BUTTON_PROFILE_SETUP, ACTION_SETUP)]]
        )
    elif not is_admin:
        lines.append(texts.PROFILE_ADMIN_ONLY)
    else:
        lines.append(texts.PROFILE_ACCEPTING_UNAVAILABLE)
    rows.append([edit])
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


@actions.action(ACTION_SETUP)
async def _setup(ctx: BotContext, claimed: ClaimedAction) -> None:
    await provider_setup.start(ctx)


@actions.action(ACTION_ACCEPTING)
async def _toggle_accepting(ctx: BotContext, claimed: ClaimedAction) -> None:
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    accepting = bool(claimed.params.get("accepting"))
    await providers.set_accepting_new_requests(actor, accepting, idem=claimed.idempotency)
    await ctx.reply(
        texts.PROFILE_ACCEPTING_SAVED_ON if accepting else texts.PROFILE_ACCEPTING_SAVED_OFF
    )
    await _send_profile(ctx)
