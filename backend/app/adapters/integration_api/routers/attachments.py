from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.adapters.app_api.routers.attachments import CHUNK, content_response, upload_fingerprint
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES, ErrorResponse
from app.adapters.integration_api.deps import AttachmentRead, Idem, RequestsWrite
from app.core import ids
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.files.api import AttachmentView

router = APIRouter(tags=["attachments"], responses=STANDARD_ERROR_RESPONSES)

UPLOAD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "Файл больше допустимого размера."},
    415: {
        "model": ErrorResponse,
        "description": "Формат файла не поддерживается (тип определяется по содержимому).",
    },
}


async def _stream(upload: UploadFile) -> Any:
    while True:
        chunk = await upload.read(CHUNK)
        if not chunk:
            return
        yield chunk


@router.post(
    "/requests/{request_id}/attachments",
    response_model=AttachmentView,
    status_code=201,
    responses=UPLOAD_ERROR_RESPONSES,
    description=(
        "Multipart с полем `file`. Повтор с тем же `Idempotency-Key` и тем же содержимым "
        "возвращает прежний результат; другой файл под тем же ключом — "
        "`409 IDEMPOTENCY_CONFLICT`."
    ),
)
async def upload_attachment(
    actor: RequestsWrite,
    request: Request,
    request_id: str,
    idem: Idem,
    file: Annotated[UploadFile, File()],
    slot: Annotated[str | None, Form()] = None,
    message_id: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > get_settings().max_upload_bytes + CHUNK:
        raise files.FileTooLarge()
    owner = (
        files.message_owner(ids.decode("message", message_id))
        if message_id
        else files.request_owner(ids.decode("request", request_id))
    )
    fingerprint = await upload_fingerprint(file)
    result = await files.upload_attachment(
        actor,
        owner=owner,
        purpose=slot,
        filename_hint=file.filename,
        content_type_hint=file.content_type,
        stream=_stream(file),
        idem=idem.of({"slot": slot, "message_id": message_id, **fingerprint}),
    )
    return result.body


@router.get(
    "/attachments/{attachment_id}/content",
    description=(
        "Вложение заявки — по scope `requests:read`, вложение карточки биржи — "
        "по `marketplace:read`: какой нужен, определяется владельцем файла."
    ),
)
async def download_attachment(
    actor: AttachmentRead,
    attachment_id: str,
    variant: Annotated[str, Query()] = "safe",
) -> StreamingResponse:
    return content_response(
        await files.open_attachment(actor, ids.decode("attachment", attachment_id), variant)
    )
