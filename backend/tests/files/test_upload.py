from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.enums import AttachmentState, VisibilityClass
from app.infra.config import Settings
from app.modules.files import api as files
from app.modules.files.errors import FileTooLarge, UnsupportedMediaType
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_upload_puts_row_in_quarantine(world: World, storage_root: Path) -> None:
    draft = await request_helpers.make_draft(world)
    result = await helpers.upload(
        world.employee,
        files.request_owner(request_helpers.rid(draft)),
        helpers.png(),
        slot="overview",
    )

    assert result.status == 201
    assert result.body["processing_state"] == AttachmentState.QUARANTINED
    assert result.body["visibility_class"] == VisibilityClass.REQUEST_PRIVATE
    assert len(helpers.stored_files(storage_root)) == 1


async def test_nameplate_slot_is_sensitive(world: World) -> None:
    draft = await request_helpers.make_draft(world)
    result = await helpers.upload(
        world.employee,
        files.request_owner(request_helpers.rid(draft)),
        helpers.png(),
        slot="nameplate",
    )
    assert result.body["visibility_class"] == VisibilityClass.REQUEST_SENSITIVE


async def test_oversized_upload_keeps_draft_and_leaves_no_file(
    world: World, storage_root: Path, override: Callable[..., Settings]
) -> None:
    draft = await request_helpers.make_draft(world)
    request_id = request_helpers.rid(draft)
    first = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.png(), slot="overview"
    )
    override(MAX_UPLOAD_BYTES="1024")

    with pytest.raises(FileTooLarge) as exc:
        await helpers.upload(
            world.employee,
            files.request_owner(request_id),
            b"",
            stream=helpers.endless_stream(b"\xff\xd8\xff" + b"\x00" * 2048),
        )

    assert exc.value.status == 413
    assert exc.value.code == "FILE_TOO_LARGE"
    assert len(helpers.stored_files(storage_root)) == 1
    view = await requests_api.get_request(world.employee, request_id)
    assert view.version == draft["version"]
    assert [item.id for item in view.attachments] == [first.body["id"]]


async def test_fake_image_is_refused_before_saving(world: World, storage_root: Path) -> None:
    draft = await request_helpers.make_draft(world)
    with pytest.raises(UnsupportedMediaType) as exc:
        await helpers.upload(
            world.employee,
            files.request_owner(request_helpers.rid(draft)),
            helpers.not_an_image(),
        )

    assert exc.value.status == 415
    assert exc.value.code == "UNSUPPORTED_MEDIA_TYPE"
    assert helpers.stored_files(storage_root) == []


async def test_photo_limit_per_request(world: World, override: Callable[..., Settings]) -> None:
    override(MAX_PHOTOS_PER_REQUEST="2")
    draft = await request_helpers.make_draft(world)
    request_id = request_helpers.rid(draft)
    for _ in range(2):
        await helpers.upload(world.employee, files.request_owner(request_id), helpers.png())

    with pytest.raises(ValidationFailed) as exc:
        await helpers.upload(world.employee, files.request_owner(request_id), helpers.png())
    assert exc.value.code == "PHOTO_LIMIT_REACHED"


async def test_foreign_customer_cannot_upload(world: World, other_world: World) -> None:
    draft = await request_helpers.make_draft(world)
    with pytest.raises(NotFound):
        await helpers.upload(
            other_world.manager,
            files.request_owner(request_helpers.rid(draft)),
            helpers.png(),
        )


async def test_employee_of_other_location_cannot_upload(world: World) -> None:
    draft = await request_helpers.make_draft(world)
    with pytest.raises(NotFound):
        await helpers.upload(
            world.other_employee,
            files.request_owner(request_helpers.rid(draft)),
            helpers.png(),
        )


async def test_author_deletes_only_until_submit(world: World, storage_root: Path) -> None:
    draft = await request_helpers.make_draft(world)
    request_id = request_helpers.rid(draft)
    uploaded = await helpers.upload(world.employee, files.request_owner(request_id), helpers.png())
    attachment_id = helpers.aid(uploaded.body)

    with pytest.raises(NotFound):
        await files.delete_attachment(world.manager, attachment_id)

    await files.delete_attachment(world.employee, attachment_id)
    assert helpers.stored_files(storage_root) == []

    again = await helpers.upload(world.employee, files.request_owner(request_id), helpers.png())
    submitted = await request_helpers.make_submitted(world)
    posted = await helpers.upload(
        world.employee, files.request_owner(request_helpers.rid(submitted)), helpers.png()
    )
    assert posted.status == 201
    with pytest.raises(Conflict):
        await files.delete_attachment(world.employee, helpers.aid(posted.body))
    assert helpers.aid(again.body)
