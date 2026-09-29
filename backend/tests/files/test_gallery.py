import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, run_command
from app.db import session as db_session
from app.db.enums import ModerationStatus, VisibilityClass
from app.db.models import Attachment
from app.infra.config import Settings
from app.modules.files import api as files
from app.modules.providers import api as providers
from tests import factories as base_factories
from tests import support
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _portfolio_image(world: World) -> uuid.UUID:
    result = await files.submit_portfolio_image(
        world.provider_admin, stream=helpers.stream_of(helpers.png())
    )
    await helpers.process()
    return helpers.aid(result.body)


async def test_portfolio_image_waits_for_moderation(world: World) -> None:
    attachment_id = await _portfolio_image(world)
    assert await helpers.publication_state(attachment_id) == ModerationStatus.PENDING

    with pytest.raises(NotFound):
        await files.open_attachment(world.manager, attachment_id)

    operator = await support.make_operator("gallery-op")
    await files.approve_attachment(operator, attachment_id)
    assert await helpers.publication_state(attachment_id) == ModerationStatus.PUBLISHED
    assert await helpers.read_content(world.manager, attachment_id)


async def test_only_provider_admin_manages_gallery(world: World) -> None:
    with pytest.raises(Forbidden):
        await files.submit_portfolio_image(
            world.dispatcher, stream=helpers.stream_of(helpers.png())
        )


async def test_portfolio_limit(world: World, override: Callable[..., Settings]) -> None:
    override(PORTFOLIO_MAX_IMAGES="2")
    for _ in range(2):
        await files.submit_portfolio_image(
            world.provider_admin, stream=helpers.stream_of(helpers.png())
        )
    with pytest.raises(ValidationFailed) as exc:
        await files.submit_portfolio_image(
            world.provider_admin, stream=helpers.stream_of(helpers.png())
        )
    assert exc.value.code == "PORTFOLIO_LIMIT_REACHED"

    avatar = await files.submit_portfolio_image(
        world.provider_admin, purpose=files.AVATAR_PURPOSE, stream=helpers.stream_of(helpers.png())
    )
    assert avatar.body["slot"] == files.AVATAR_PURPOSE


async def test_rejection_requires_reason(world: World) -> None:
    attachment_id = await _portfolio_image(world)
    operator = await support.make_operator("gallery-op-2")
    with pytest.raises(ValidationFailed):
        await files.reject_attachment(operator, attachment_id, reason="  ")

    await files.reject_attachment(operator, attachment_id, reason="Чужой логотип")
    assert await helpers.publication_state(attachment_id) == ModerationStatus.REJECTED
    with pytest.raises(NotFound):
        await files.open_attachment(world.manager, attachment_id)


async def test_moderation_queue_is_operator_only(world: World) -> None:
    await _portfolio_image(world)
    operator = await support.make_operator("queue-op")
    items, _ = await files.list_moderation_queue(operator)
    assert [item.visibility_class for item in items] == [VisibilityClass.PROFILE_PUBLIC]
    with pytest.raises(Forbidden):
        await files.list_moderation_queue(world.provider_admin)


async def test_review_photos_are_separate_copies(world: World) -> None:
    completed = await request_helpers.make_completion_reported(world)
    request_id = request_helpers.rid(completed)
    photo = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="overview"
    )
    await helpers.process()
    source_id = helpers.aid(photo.body)

    async with db_session.transaction() as session:
        review = await base_factories.create_review(
            session,
            request_id=request_id,
            assignment_id=request_helpers.assignment_id(completed),
            customer_org_id=world.customer_org_id,
            provider_org_id=world.provider_org_id,
            author_membership_id=world.manager.membership_id,
        )
        review_id = review.id

    async def handler(ctx: CommandContext) -> CommandResult:
        copies = await files.attach_review_photos(ctx, review_id, [source_id])
        return CommandResult({"copies": [str(value) for value in copies]})

    result = await run_command(world.manager, handler)
    copy_id = uuid.UUID(result.body["copies"][0])
    copy = await helpers.attachment(copy_id)
    assert copy.visibility_class == VisibilityClass.REVIEW_PUBLIC
    assert copy.review_id == review_id
    assert copy.storage_key != (await helpers.attachment(source_id)).storage_key
    assert await helpers.publication_state(copy_id) == ModerationStatus.PENDING

    operator = await support.make_operator("review-op")
    await files.approve_attachment(operator, copy_id)
    assert not helpers.has_gps(await helpers.read_content(world.dispatcher, copy_id))


async def _review_with_photo(world: World, slot: str) -> tuple[uuid.UUID, uuid.UUID]:
    completed = await request_helpers.make_completion_reported(world)
    request_id = request_helpers.rid(completed)
    photo = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.jpeg_with_gps(), slot=slot
    )
    await helpers.process()
    async with db_session.transaction() as session:
        review = await base_factories.create_review(
            session,
            request_id=request_id,
            assignment_id=request_helpers.assignment_id(completed),
            customer_org_id=world.customer_org_id,
            provider_org_id=world.provider_org_id,
            author_membership_id=world.manager.membership_id,
        )
        return review.id, helpers.aid(photo.body)


async def test_nameplate_goes_to_review_only_when_confirmed(world: World) -> None:
    review_id, source_id = await _review_with_photo(world, "nameplate")

    def attach(confirm: bool) -> Callable[[CommandContext], object]:
        async def handler(ctx: CommandContext) -> CommandResult:
            copies = await files.attach_review_photos(
                ctx, review_id, [source_id], confirm_sensitive=confirm
            )
            return CommandResult({"copies": [str(value) for value in copies]})

        return handler

    with pytest.raises(ValidationFailed) as exc:
        await run_command(world.manager, attach(False))  # type: ignore[arg-type]
    assert exc.value.code == "SENSITIVE_PHOTO_NOT_CONFIRMED"

    result = await run_command(world.manager, attach(True))  # type: ignore[arg-type]
    assert len(result.body["copies"]) == 1


async def test_photo_author_cannot_delete_review_copy(world: World) -> None:
    review_id, source_id = await _review_with_photo(world, "overview")

    async def handler(ctx: CommandContext) -> CommandResult:
        copies = await files.attach_review_photos(ctx, review_id, [source_id])
        return CommandResult({"copy": str(copies[0])})

    copy_id = uuid.UUID((await run_command(world.manager, handler)).body["copy"])
    with pytest.raises(NotFound):
        await files.delete_attachment(world.employee, copy_id)
    assert (await helpers.attachment(copy_id)).review_id == review_id


async def test_cleanup_removes_rejected_files(world: World, storage_root: Path) -> None:
    draft = await request_helpers.make_draft(world)
    uploaded = await helpers.upload(
        world.employee,
        files.request_owner(request_helpers.rid(draft)),
        helpers.fake_jpeg(),
        slot="overview",
    )
    await helpers.process()
    attachment_id = helpers.aid(uploaded.body)
    async with db_session.transaction() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == attachment_id)
            .values(updated_at=utcnow() - timedelta(days=30))
        )

    assert await files.cleanup_files(utcnow()) == 1
    assert helpers.stored_files(storage_root) == []
    async with db_session.transaction() as session:
        assert await session.get(Attachment, attachment_id) is None


async def test_public_profile_gallery_lists_only_published_works(world: World) -> None:
    pending = await _portfolio_image(world)
    approved = await _portfolio_image(world)
    avatar = await files.submit_portfolio_image(
        world.provider_admin, purpose=files.AVATAR_PURPOSE, stream=helpers.stream_of(helpers.png())
    )
    await helpers.process()
    operator = await support.make_operator("gallery-public-op")
    await files.approve_attachment(operator, approved)
    await files.approve_attachment(operator, helpers.aid(avatar.body))

    profile = await providers.get_public_profile(world.provider_org_id)
    assert profile.gallery == [ids.encode("attachment", approved)]
    assert ids.encode("attachment", pending) not in profile.gallery
