import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from app.core import ids
from app.db.models import Attachment

MIME_BY_FORMAT = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
EXTENSION_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class AttachmentView(BaseModel):
    id: str
    owner_kind: str
    request_id: str | None = None
    message_id: str | None = None
    equipment_id: str | None = None
    slot: str | None = None
    visibility_class: str
    processing_state: str
    publication_state: str | None = None
    rejected_reason: str | None = None
    mime_type: str
    byte_size: int
    pixel_width: int | None = None
    pixel_height: int | None = None
    created_at: datetime
    caption: str | None = None


class GalleryItemView(BaseModel):
    id: str
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentContent:
    attachment_id: uuid.UUID
    filename: str
    mime_type: str
    byte_size: int
    stream: AsyncIterator[bytes]


def server_filename(attachment_id: uuid.UUID, mime_type: str, *, variant: str) -> str:
    extension = EXTENSION_BY_MIME.get(mime_type, "bin")
    suffix = "" if variant == "safe" else f"-{variant}"
    return f"{ids.encode('attachment', attachment_id)}{suffix}.{extension}"


def to_attachment_view(attachment: Attachment) -> AttachmentView:
    return AttachmentView(
        id=ids.encode("attachment", attachment.id),
        owner_kind=attachment.owner_kind,
        request_id=ids.encode_opt("request", attachment.request_id),
        message_id=ids.encode_opt("message", attachment.message_id),
        equipment_id=ids.encode_opt("equipment", attachment.equipment_id),
        slot=attachment.slot,
        visibility_class=attachment.visibility_class,
        processing_state=attachment.processing_state,
        publication_state=attachment.publication_state,
        rejected_reason=_public_reason(attachment),
        mime_type=attachment.mime_type,
        byte_size=attachment.byte_size,
        pixel_width=attachment.pixel_width,
        pixel_height=attachment.pixel_height,
        created_at=attachment.created_at,
        caption=attachment.caption if attachment.owner_kind == "profile" else None,
    )


def _public_reason(attachment: Attachment) -> str | None:
    if attachment.processing_state != "rejected":
        return None
    return attachment.rejected_reason
