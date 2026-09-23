from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.adapters.app_api.routers.attachments import content_response
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.operator.deps import CurrentOperator, IdemKey
from app.adapters.operator.schemas import Page, RevokeBody, page_of
from app.core import ids
from app.modules.files import api as files
from app.modules.files.api import AttachmentView

router = APIRouter(prefix="/attachments", tags=["operator"], responses=STANDARD_ERROR_RESPONSES)


@router.get("", response_model=Page[AttachmentView])
async def list_queue(
    operator: CurrentOperator,
    status: Annotated[str, Query()] = "pending",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[AttachmentView]:
    items, next_cursor = await files.list_moderation_queue(
        operator,
        status=status,
        cursor=ids.decode("moderation_case", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "moderation_case", next_cursor)


@router.post("/{attachment_id}/approve", response_model=AttachmentView)
async def approve(
    operator: CurrentOperator, attachment_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /attachments/approve", {"id": attachment_id})
    result = await files.approve_attachment(
        operator, ids.decode("attachment", attachment_id), idem=idem
    )
    return result.body


@router.post("/{attachment_id}/reject", response_model=AttachmentView)
async def reject(
    operator: CurrentOperator, attachment_id: str, body: RevokeBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, "POST /attachments/reject", {"id": attachment_id, "reason": body.reason}
    )
    result = await files.reject_attachment(
        operator, ids.decode("attachment", attachment_id), reason=body.reason, idem=idem
    )
    return result.body


@router.get("/{attachment_id}/content")
async def download(
    operator: CurrentOperator,
    attachment_id: str,
    variant: Annotated[str, Query()] = "safe",
) -> StreamingResponse:
    return content_response(
        await files.open_attachment(operator, ids.decode("attachment", attachment_id), variant)
    )
