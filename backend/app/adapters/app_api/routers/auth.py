from fastapi import APIRouter, Depends, Response

from app.adapters.app_api.deps import CurrentSession
from app.adapters.app_api.schemas import (
    AuthResponse,
    DemoLogin,
    InitDataLogin,
    LinkAuthResponse,
    LinkLogin,
    MeResponse,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.ratelimit import limit_auth_attempts
from app.core import ids
from app.modules.identity import api as identity
from app.modules.identity.api import SessionIssued, UserView

router = APIRouter(tags=["auth"], responses=STANDARD_ERROR_RESPONSES)
demo_router = APIRouter(tags=["auth"], responses=STANDARD_ERROR_RESPONSES)


def _auth_response(issued: SessionIssued) -> AuthResponse:
    return AuthResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        user=issued.user,
        memberships=issued.memberships,
        organizations=issued.organizations,
    )


@router.post("/auth/max", response_model=AuthResponse, dependencies=[Depends(limit_auth_attempts)])
async def login_with_max(body: InitDataLogin) -> AuthResponse:
    return _auth_response(await identity.login_with_init_data(body.init_data))


@router.post(
    "/auth/link", response_model=LinkAuthResponse, dependencies=[Depends(limit_auth_attempts)]
)
async def login_with_link(body: LinkLogin) -> LinkAuthResponse:
    """Вход по одноразовой ссылке из бота (D-S3): токен только в теле запроса."""
    result = await identity.login_with_link(body.token)
    issued = result.issued
    return LinkAuthResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        user=issued.user,
        memberships=issued.memberships,
        organizations=issued.organizations,
        target=result.target,
    )


@demo_router.post(
    "/auth/demo", response_model=AuthResponse, dependencies=[Depends(limit_auth_attempts)]
)
async def login_demo(body: DemoLogin) -> AuthResponse:
    return _auth_response(await identity.login_demo(body.user_key))


@router.get("/me", response_model=MeResponse)
async def me(session: CurrentSession) -> MeResponse:
    memberships = await identity.list_user_memberships(session.user_id)
    return MeResponse(
        user=UserView(id=ids.encode("user", session.user_id), display_name=session.display_name),
        memberships=memberships,
        organizations=identity.organizations_of(memberships),
    )


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(session: CurrentSession) -> Response:
    await identity.logout(session)
    return Response(status_code=204)
