from typing import Annotated

from fastapi import Depends, Header

from app.adapters.http.idempotency import idempotency_key_header
from app.core.actor import OperatorActor
from app.core.errors import Unauthenticated
from app.modules.identity import api as identity

_BEARER = "bearer "


async def current_operator(
    authorization: Annotated[str | None, Header()] = None,
) -> OperatorActor:
    if not authorization or not authorization.lower().startswith(_BEARER):
        raise Unauthenticated()
    token = authorization[len(_BEARER) :].strip()
    if not token:
        raise Unauthenticated()
    session = await identity.authenticate_session(token)
    return await identity.resolve_operator(session)


CurrentOperator = Annotated[OperatorActor, Depends(current_operator)]
IdemKey = Annotated[str, Depends(idempotency_key_header)]
