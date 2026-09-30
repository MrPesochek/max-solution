import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.core import ids
from app.core.actor import Actor
from app.core.clock import utcnow
from app.core.pipeline import CommandResult
from app.db import session as db_session
from app.db.models import Attachment, AttachmentVariant, ModerationCase
from app.modules.files import api as files
from app.modules.files.owners import AttachmentOwner


def jpeg_with_gps(size: tuple[int, int] = (64, 48)) -> bytes:
    img = Image.new("RGB", size, (180, 60, 40))
    exif = img.getexif()
    exif[0x0112] = 3
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (IFDRational(55, 1), IFDRational(45, 1), IFDRational(0, 1))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def png(size: tuple[int, int] = (40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def fake_jpeg() -> bytes:
    return b"\xff\xd8\xff" + b"not an image at all" * 8


def not_an_image() -> bytes:
    return b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"


def has_gps(data: bytes) -> bool:
    exif = Image.open(io.BytesIO(data)).getexif()
    return bool(exif) and bool(exif.get_ifd(0x8825))


async def stream_of(data: bytes, *, chunk: int = 1024) -> AsyncIterator[bytes]:
    for start in range(0, len(data), chunk):
        yield data[start : start + chunk]


async def endless_stream(chunk: bytes) -> AsyncIterator[bytes]:
    yield chunk
    while True:
        yield b"\x00" * len(chunk)


async def upload(
    actor: Actor,
    owner: AttachmentOwner,
    data: bytes,
    *,
    slot: str | None = None,
    stream: AsyncIterator[bytes] | None = None,
) -> CommandResult:
    return await files.upload_attachment(
        actor,
        owner=owner,
        purpose=slot,
        filename_hint="photo.jpg",
        content_type_hint="image/jpeg",
        stream=stream if stream is not None else stream_of(data),
    )


def aid(body: dict[str, Any]) -> uuid.UUID:
    return ids.decode("attachment", body["id"])


async def process() -> int:
    return await files.process_images(utcnow())


async def upload_and_process(
    actor: Actor, owner: AttachmentOwner, data: bytes, *, slot: str | None = None
) -> uuid.UUID:
    result = await upload(actor, owner, data, slot=slot)
    await process()
    return aid(result.body)


async def attachment(attachment_id: uuid.UUID) -> Attachment:
    async with db_session.transaction() as session:
        row = await session.get(Attachment, attachment_id)
        assert row is not None
        return row


async def variants(attachment_id: uuid.UUID) -> list[AttachmentVariant]:
    async with db_session.transaction() as session:
        from sqlalchemy import select

        stmt = select(AttachmentVariant).where(AttachmentVariant.attachment_id == attachment_id)
        return list((await session.execute(stmt)).scalars().all())


async def publication_state(attachment_id: uuid.UUID) -> str | None:
    async with db_session.transaction() as session:
        from sqlalchemy import select

        stmt = select(ModerationCase.status).where(ModerationCase.attachment_id == attachment_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def read_content(actor: Actor, attachment_id: uuid.UUID, variant: str = "safe") -> bytes:
    content = await files.open_attachment(actor, attachment_id, variant)
    return b"".join([chunk async for chunk in content.stream])


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]
