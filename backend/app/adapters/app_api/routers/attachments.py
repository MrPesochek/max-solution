import hashlib
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.adapters.app_api.deps import CurrentActor, IdemKey, OrgActor
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.core.actor import Actor
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.files.api import AttachmentView

router = APIRouter(tags=["attachments"], responses=STANDARD_ERROR_RESPONSES)

CHUNK = 64 * 1024


class AttachmentDeletedView(BaseModel):
    id: str
    deleted: bool


def _chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    async def stream() -> AsyncIterator[bytes]:
        while True:
            chunk = await upload.read(CHUNK)
            if not chunk:
                return
            yield chunk

    return stream()


async def upload_fingerprint(upload: UploadFile) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    while chunk := await upload.read(CHUNK):
        digest.update(chunk)
        size += len(chunk)
    await upload.seek(0)
    return {"filename": upload.filename, "size": size, "sha256": digest.hexdigest()}


def _guard_length(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > get_settings().max_upload_bytes + CHUNK:
        raise files.FileTooLarge()


async def _upload(
    actor: Actor,
    request: Request,
    owner: files.AttachmentOwner,
    *,
    slot: str | None,
    file: UploadFile,
    idem_key: str,
    operation: str,
) -> dict[str, Any]:
    _guard_length(request)
    idem = make_idempotency(idem_key, operation, {"slot": slot, **await upload_fingerprint(file)})
    result = await files.upload_attachment(
        actor,
        owner=owner,
        purpose=slot,
        filename_hint=file.filename,
        content_type_hint=file.content_type,
        stream=_chunks(file),
        idem=idem,
    )
    return result.body


@router.post("/requests/{request_id}/attachments", response_model=AttachmentView, status_code=201)
async def upload_request_attachment(
    actor: OrgActor,
    request: Request,
    request_id: str,
    idem_key: IdemKey,
    file: Annotated[UploadFile, File()],
    slot: Annotated[str | None, Form()] = None,
    message_id: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    owner = (
        files.message_owner(ids.decode("message", message_id))
        if message_id
        else files.request_owner(ids.decode("request", request_id))
    )
    return await _upload(
        actor,
        request,
        owner,
        slot=slot,
        file=file,
        idem_key=idem_key,
        operation="POST /requests/attachments",
    )


@router.get("/requests/{request_id}/attachments", response_model=list[AttachmentView])
async def list_request_attachments(actor: CurrentActor, request_id: str) -> list[AttachmentView]:
    return await files.list_for_request(actor, ids.decode("request", request_id))


@router.get("/attachments/{attachment_id}", response_model=AttachmentView)
async def get_attachment(actor: CurrentActor, attachment_id: str) -> AttachmentView:
    return await files.get_attachment(actor, ids.decode("attachment", attachment_id))


@router.get("/attachments/{attachment_id}/content")
async def download_attachment(
    actor: CurrentActor,
    attachment_id: str,
    variant: Annotated[str, Query()] = "safe",
) -> StreamingResponse:
    return content_response(
        await files.open_attachment(actor, ids.decode("attachment", attachment_id), variant)
    )


@router.delete("/attachments/{attachment_id}", response_model=AttachmentDeletedView)
async def delete_attachment(
    actor: OrgActor, attachment_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "DELETE /attachments", {"id": attachment_id})
    result = await files.delete_attachment(
        actor, ids.decode("attachment", attachment_id), idem=idem
    )
    return result.body


@router.post("/equipment/{equipment_id}/photos", response_model=AttachmentView, status_code=201)
async def upload_equipment_photo(
    actor: OrgActor,
    request: Request,
    equipment_id: str,
    idem_key: IdemKey,
    file: Annotated[UploadFile, File()],
    slot: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    return await _upload(
        actor,
        request,
        files.equipment_owner(ids.decode("equipment", equipment_id)),
        slot=slot,
        file=file,
        idem_key=idem_key,
        operation="POST /equipment/photos",
    )


@router.get("/equipment/{equipment_id}/photos", response_model=list[AttachmentView])
async def list_equipment_photos(actor: CurrentActor, equipment_id: str) -> list[AttachmentView]:
    return await files.list_for_equipment(actor, ids.decode("equipment", equipment_id))


@router.post("/provider-profile/portfolio", response_model=AttachmentView, status_code=201)
async def upload_portfolio_image(
    actor: OrgActor,
    request: Request,
    idem_key: IdemKey,
    file: Annotated[UploadFile, File()],
    slot: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    _guard_length(request)
    idem = make_idempotency(
        idem_key, "POST /provider-profile/portfolio", {"slot": slot, "filename": file.filename}
    )
    result = await files.submit_portfolio_image(
        actor,
        purpose=slot or files.PORTFOLIO_PURPOSE,
        filename_hint=file.filename,
        content_type_hint=file.content_type,
        stream=_chunks(file),
        idem=idem,
    )
    return result.body


@router.get("/provider-profile/portfolio", response_model=list[AttachmentView])
async def list_portfolio(actor: OrgActor) -> list[AttachmentView]:
    return await files.list_portfolio(actor)


class PortfolioCaptionBody(BaseModel):
    caption: Annotated[str, Field(max_length=200)] | None = None


@router.patch("/provider-profile/portfolio/{attachment_id}", response_model=AttachmentView)
async def update_portfolio_caption(
    actor: OrgActor, attachment_id: str, body: PortfolioCaptionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"PATCH /provider-profile/portfolio/{attachment_id}", body.model_dump()
    )
    result = await files.set_portfolio_caption(
        actor, ids.decode("attachment", attachment_id), body.caption, idem=idem
    )
    return result.body


@router.delete("/provider-profile/portfolio/{attachment_id}", response_model=AttachmentDeletedView)
async def delete_portfolio_image(
    actor: OrgActor, attachment_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "DELETE /provider-profile/portfolio", {"id": attachment_id})
    result = await files.delete_attachment(
        actor, ids.decode("attachment", attachment_id), idem=idem
    )
    return result.body


@router.post("/verification/attachments", response_model=AttachmentView, status_code=201)
async def upload_verification_evidence(
    actor: OrgActor,
    request: Request,
    idem_key: IdemKey,
    file: Annotated[UploadFile, File()],
    verification_case_id: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    owner = files.verification_owner(
        ids.decode("verification_case", verification_case_id) if verification_case_id else None
    )
    return await _upload(
        actor,
        request,
        owner,
        slot=None,
        file=file,
        idem_key=idem_key,
        operation="POST /verification/attachments",
    )


def content_response(content: files.AttachmentContent) -> StreamingResponse:
    return StreamingResponse(
        content.stream,
        media_type=content.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{content.filename}"',
            "Content-Length": str(content.byte_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
