from typing import Any

from fastapi import APIRouter

from app.adapters.app_api.deps import IdemKey, OrgActor
from app.adapters.app_api.schemas import VerificationInformationBody
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.modules.trust import api as trust
from app.modules.trust.api import VerificationCaseView, VerificationInformationSubmittedView

router = APIRouter(
    prefix="/verification", tags=["verification"], responses=STANDARD_ERROR_RESPONSES
)


@router.get("", response_model=list[VerificationCaseView])
async def list_cases(actor: OrgActor) -> list[VerificationCaseView]:
    return await trust.list_verification_cases(actor)


@router.post("", response_model=VerificationInformationSubmittedView)
async def submit_information(
    actor: OrgActor, body: VerificationInformationBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = trust.VerificationInformationData(note=body.note, attachment_refs=body.attachment_refs)
    idem = make_idempotency(idem_key, "POST /verification", body.model_dump())
    result = await trust.submit_verification_information(actor, data, idem=idem)
    return result.body
