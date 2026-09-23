from typing import Annotated

from fastapi import Depends, Header

from app.adapters.http.idempotency import idempotency_key_header
from app.core.actor import Actor, UserActor
from app.core.errors import Forbidden, Unauthenticated
from app.core.scope import AccessScope, scope_of
from app.modules.identity import api as identity

_BEARER = "bearer "


async def current_session(
    authorization: Annotated[str | None, Header()] = None,
) -> identity.SessionInfo:
    if not authorization or not authorization.lower().startswith(_BEARER):
        raise Unauthenticated()
    token = authorization[len(_BEARER) :].strip()
    if not token:
        raise Unauthenticated()
    return await identity.authenticate_session(token)


CurrentSession = Annotated[identity.SessionInfo, Depends(current_session)]


async def current_actor(
    session: CurrentSession,
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
    x_membership_id: Annotated[str | None, Header(alias="X-Membership-Id")] = None,
) -> Actor:
    return await identity.resolve_actor(session, x_organization_id, x_membership_id)


CurrentActor = Annotated[Actor, Depends(current_actor)]


async def current_org_actor(actor: CurrentActor) -> UserActor:
    if not isinstance(actor, UserActor):
        raise Forbidden("Укажите членство в заголовке X-Membership-Id или X-Organization-Id")
    return actor


OrgActor = Annotated[UserActor, Depends(current_org_actor)]


def current_scope(actor: OrgActor) -> AccessScope:
    return scope_of(actor)


Scope = Annotated[AccessScope, Depends(current_scope)]

IdemKey = Annotated[str, Depends(idempotency_key_header)]
