import uuid
from typing import Any

import pytest

from app.core.errors import NotFound, ValidationFailed
from app.db.enums import AttachmentState, ModerationStatus, VisibilityClass
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import factories as request_factories
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _draft_with_photos(world: World) -> tuple[dict[str, Any], uuid.UUID, uuid.UUID]:
    draft = await request_helpers.make_marketplace_draft(world)
    request_id = request_helpers.rid(draft)
    private = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="overview"
    )
    nameplate = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="nameplate"
    )
    await helpers.process()
    return draft, helpers.aid(private.body), helpers.aid(nameplate.body)


async def test_private_photo_reaches_card_only_as_separate_copy(world: World) -> None:
    rival = await request_factories.build_rival_provider(world)
    draft, private_id, _ = await _draft_with_photos(world)
    request_id = request_helpers.rid(draft)

    published = await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(attachment_ids=(private_id,)),
        expected_version=draft["version"],
    )

    card = await request_helpers.public_card(published.body)
    assert len(card.published_attachment_ids) == 1
    copy_id = card.published_attachment_ids[0]
    assert copy_id != private_id

    copy = await helpers.attachment(copy_id)
    source = await helpers.attachment(private_id)
    assert copy.visibility_class == VisibilityClass.PUBLIC_CARD
    assert source.visibility_class == VisibilityClass.REQUEST_PRIVATE
    assert copy.storage_key != source.storage_key
    assert copy.processing_state == AttachmentState.READY
    assert copy.source_attachment_id == private_id
    assert copy.publication_state == ModerationStatus.PUBLISHED

    assert not helpers.has_gps(await helpers.read_content(rival.dispatcher, copy_id))
    with pytest.raises(NotFound):
        await files.open_attachment(rival.dispatcher, private_id)


async def test_nothing_is_published_without_explicit_choice(world: World) -> None:
    rival = await request_factories.build_rival_provider(world)
    draft, private_id, _ = await _draft_with_photos(world)

    published = await requests_api.publish_search(
        world.manager, request_helpers.rid(draft), expected_version=draft["version"]
    )
    card = await request_helpers.public_card(published.body)
    assert card.published_attachment_ids == []
    with pytest.raises(NotFound):
        await files.open_attachment(rival.dispatcher, private_id)


async def test_sensitive_photo_requires_confirmation(world: World) -> None:
    await request_factories.build_rival_provider(world)
    draft, private_id, nameplate_id = await _draft_with_photos(world)
    request_id = request_helpers.rid(draft)

    with pytest.raises(ValidationFailed) as exc:
        await requests_api.publish_search(
            world.manager,
            request_id,
            data=requests_api.PublicCardInput(attachment_ids=(private_id, nameplate_id)),
            expected_version=draft["version"],
        )
    assert exc.value.code == "SENSITIVE_PHOTO_NOT_CONFIRMED"

    published = await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(
            attachment_ids=(private_id, nameplate_id), confirm_sensitive=True
        ),
        expected_version=draft["version"],
    )
    card = await request_helpers.public_card(published.body)
    assert len(card.published_attachment_ids) == 2


async def test_unpublished_card_stops_serving_copies(world: World) -> None:
    rival = await request_factories.build_rival_provider(world)
    draft, private_id, _ = await _draft_with_photos(world)
    request_id = request_helpers.rid(draft)

    published = await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(attachment_ids=(private_id,)),
        expected_version=draft["version"],
    )
    copy_id = (await request_helpers.public_card(published.body)).published_attachment_ids[0]
    assert await helpers.read_content(rival.dispatcher, copy_id)

    await requests_api.request_cancellation(
        world.manager,
        request_id,
        target="cancel_request",
        reason="Решили своими силами",
        expected_version=published.body["version"],
    )

    assert await helpers.publication_state(copy_id) == ModerationStatus.REMOVED
    assert (await helpers.attachment(copy_id)).publication_state == ModerationStatus.REMOVED
    with pytest.raises(NotFound):
        await files.open_attachment(rival.dispatcher, copy_id)


async def test_only_ready_photo_can_be_published(world: World) -> None:
    await request_factories.build_rival_provider(world)
    draft = await request_helpers.make_marketplace_draft(world)
    request_id = request_helpers.rid(draft)
    uploaded = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.png(), slot="overview"
    )

    with pytest.raises(Exception) as exc:
        await requests_api.publish_search(
            world.manager,
            request_id,
            data=requests_api.PublicCardInput(attachment_ids=(helpers.aid(uploaded.body),)),
            expected_version=draft["version"],
        )
    assert getattr(exc.value, "code", None) == "ATTACHMENT_NOT_READY"


async def test_foreign_photo_cannot_be_published(world: World, other_world: World) -> None:
    await request_factories.build_rival_provider(world)
    draft = await request_helpers.make_marketplace_draft(world)
    foreign = await request_helpers.make_draft(other_world)
    stranger = await helpers.upload(
        other_world.employee,
        files.request_owner(request_helpers.rid(foreign)),
        helpers.png(),
        slot="overview",
    )
    await helpers.process()

    with pytest.raises(NotFound):
        await requests_api.publish_search(
            world.manager,
            request_helpers.rid(draft),
            data=requests_api.PublicCardInput(attachment_ids=(helpers.aid(stranger.body),)),
            expected_version=draft["version"],
        )
