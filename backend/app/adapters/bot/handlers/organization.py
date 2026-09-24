from __future__ import annotations

from app.adapters.bot import keyboards, menu, texts
from app.adapters.bot.context import BotContext
from app.modules.identity import api as identity


@menu.menu(menu.ORGANIZATION)
async def show_organization(ctx: BotContext) -> None:
    scope = await ctx.scope()
    if scope is None:
        await ctx.reply(texts.NO_ORG_PROMPT)
        return
    organization = await identity.get_organization(scope)
    kinds = ", ".join(
        texts.ORG_KIND_CUSTOMER if kind == "customer" else texts.ORG_KIND_PROVIDER
        for kind in organization.kinds
    )
    summary = texts.ORG_SUMMARY.format(
        name=organization.name,
        kinds=kinds,
        phone=organization.contact_phone or texts.ORG_NO_PHONE,
        details=_verification(organization.details_verification_status),
    )
    await ctx.reply(
        summary,
        [keyboards.rows([keyboards.open_app(texts.ORG_MANAGE, "organization", organization.id)])],
    )


_VERIFICATION = {
    "unverified": "не проверены",
    "pending": "на проверке",
    "verified": "проверены",
    "rejected": "проверка не пройдена",
}


def _verification(status: str) -> str:
    return _VERIFICATION.get(status, status)
