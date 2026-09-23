from fastapi import APIRouter

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import AnyKey
from app.adapters.integration_api.schemas import MeResponse
from app.modules.integration import api as integration

router = APIRouter(tags=["me"], responses=STANDARD_ERROR_RESPONSES)


@router.get(
    "/me",
    response_model=MeResponse,
)
async def get_me(actor: AnyKey) -> MeResponse:
    identity = await integration.describe_actor(actor)
    return MeResponse(
        organization_id=identity.organization_id,
        organization_name=identity.organization_name,
        client_id=identity.client_id,
        client_name=identity.client_name,
        key_prefix=identity.key_prefix,
        scopes=identity.scopes,
    )
