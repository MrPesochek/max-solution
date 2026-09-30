import io
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import update

from app.core.clock import utcnow
from app.db import session as db_session
from app.db.enums import AttachmentState, AttachmentVariantKind
from app.db.models import Attachment, Organization
from app.infra.config import Settings
from app.modules.files import api as files
from tests import factories as base_factories
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _uploaded(world: World, data: bytes, *, slot: str = "overview") -> uuid.UUID:
    draft = await request_helpers.make_draft(world)
    result = await helpers.upload(
        world.employee, files.request_owner(request_helpers.rid(draft)), data, slot=slot
    )
    return helpers.aid(result.body)


async def test_ready_variants_have_no_exif(world: World, storage_root: Path) -> None:
    attachment_id = await _uploaded(world, helpers.jpeg_with_gps())
    assert await helpers.process() == 1

    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.READY
    assert row.pixel_width == 64 and row.pixel_height == 48
    kinds = {variant.variant_kind for variant in await helpers.variants(attachment_id)}
    assert kinds == {AttachmentVariantKind.SAFE_COPY, AttachmentVariantKind.PREVIEW}

    safe = await helpers.read_content(world.employee, attachment_id)
    assert not helpers.has_gps(safe)
    thumb = await helpers.read_content(world.employee, attachment_id, "thumb")
    assert max(Image.open(io.BytesIO(thumb)).size) <= 512
    assert len(helpers.stored_files(storage_root)) == 2


async def test_evidence_keeps_closed_original(world: World, storage_root: Path) -> None:
    async with db_session.transaction() as session:
        org = await session.get(Organization, world.provider_org_id)
        assert org is not None
        await base_factories.create_verification_case(session, org)

    await helpers.upload(world.provider_admin, files.verification_owner(), helpers.jpeg_with_gps())
    assert await helpers.process() == 1
    assert len(helpers.stored_files(storage_root)) == 3


async def test_fake_format_is_rejected(world: World) -> None:
    attachment_id = await _uploaded(world, helpers.fake_jpeg())
    await helpers.process()

    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.REJECTED
    assert row.rejected_reason == "decode_failed"


async def test_pixel_limit_is_rejected(world: World, override: Callable[..., Settings]) -> None:
    attachment_id = await _uploaded(world, helpers.png((60, 60)))
    override(MAX_IMAGE_PIXELS="100")
    await helpers.process()

    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.REJECTED
    assert row.rejected_reason == "too_many_pixels"


async def test_processing_survives_restart(world: World) -> None:
    attachment_id = await _uploaded(world, helpers.png())
    async with db_session.transaction() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == attachment_id)
            .values(attempt_count=1, lease_until=utcnow() - timedelta(hours=1))
        )

    assert await files.process_images(utcnow()) == 1
    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.READY
    assert row.lease_until is None


async def test_lease_skips_recently_taken_row(world: World) -> None:
    attachment_id = await _uploaded(world, helpers.png())
    async with db_session.transaction() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == attachment_id)
            .values(attempt_count=1, lease_until=utcnow() + timedelta(minutes=1))
        )
    assert await files.process_images(utcnow()) == 0


async def test_retries_are_bounded(world: World, override: Callable[..., Settings]) -> None:
    override(IMAGE_PROCESSING_MAX_ATTEMPTS="2")
    attachment_id = await _uploaded(world, helpers.png())
    async with db_session.transaction() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == attachment_id)
            .values(attempt_count=2, lease_until=utcnow() - timedelta(hours=1))
        )

    assert await files.process_images(utcnow()) == 0
    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.REJECTED
    assert row.rejected_reason == "processing_failed"


async def test_missing_file_is_rejected(world: World, storage_root: Path) -> None:
    attachment_id = await _uploaded(world, helpers.png())
    for path in helpers.stored_files(storage_root):
        path.unlink()

    await helpers.process()
    row = await helpers.attachment(attachment_id)
    assert row.processing_state == AttachmentState.REJECTED
    assert row.rejected_reason == "missing_file"
