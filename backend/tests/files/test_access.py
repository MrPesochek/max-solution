import pytest

from app.core.actor import IntegrationActor
from app.core.errors import NotFound
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _accepted_with_photos(world: World) -> tuple[dict[str, object], str, str]:
    accepted = await request_helpers.make_accepted(world)
    request_id = request_helpers.rid(accepted)
    private = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.png(), slot="overview"
    )
    sensitive = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.png(), slot="nameplate"
    )
    await helpers.process()
    return accepted, private.body["id"], sensitive.body["id"]


async def test_participants_read_both_classes(world: World) -> None:
    _, private_id, sensitive_id = await _accepted_with_photos(world)
    for actor in (world.manager, world.employee, world.dispatcher, world.provider_admin):
        for public_id in (private_id, sensitive_id):
            content = await files.open_attachment(actor, helpers.aid({"id": public_id}))
            assert content.byte_size > 0


async def test_integration_key_of_assigned_provider_reads_file(world: World) -> None:
    _, private_id, _ = await _accepted_with_photos(world)
    content = await files.open_attachment(world.integration, helpers.aid({"id": private_id}))
    assert content.mime_type == "image/png"


async def test_foreign_actors_get_not_found(world: World, other_world: World) -> None:
    _, private_id, sensitive_id = await _accepted_with_photos(world)
    attachment_id = helpers.aid({"id": private_id})
    for actor in (
        other_world.manager,
        other_world.employee,
        other_world.dispatcher,
        other_world.integration,
        world.other_employee,
    ):
        with pytest.raises(NotFound):
            await files.open_attachment(actor, attachment_id)
    with pytest.raises(NotFound):
        await files.open_attachment(other_world.manager, helpers.aid({"id": sensitive_id}))


async def test_former_provider_loses_access(world: World) -> None:
    accepted, private_id, _ = await _accepted_with_photos(world)
    request_id = request_helpers.rid(accepted)
    current = await requests_api.get_request(world.manager, request_id)
    await requests_api.withdraw_assignment(
        world.dispatcher,
        request_id,
        assignment_id=request_helpers.assignment_id(accepted),
        reason="Нет запчастей",
        expected_version=current.version,
    )

    with pytest.raises(NotFound):
        await files.open_attachment(world.dispatcher, helpers.aid({"id": private_id}))
    assert await files.list_for_request(world.dispatcher, request_id) == []


async def test_not_ready_file_is_visible_only_to_uploader(world: World) -> None:
    accepted = await request_helpers.make_accepted(world)
    request_id = request_helpers.rid(accepted)
    uploaded = await helpers.upload(
        world.employee, files.request_owner(request_id), helpers.png(), slot="overview"
    )
    attachment_id = helpers.aid(uploaded.body)

    with pytest.raises(NotFound):
        await files.open_attachment(world.employee, attachment_id)
    status = await files.get_attachment(world.employee, attachment_id)
    assert status.processing_state == "quarantined"
    with pytest.raises(NotFound):
        await files.get_attachment(world.dispatcher, attachment_id)
    assert await files.list_for_request(world.dispatcher, request_id) == []


async def test_rejected_file_is_not_served(world: World) -> None:
    accepted = await request_helpers.make_accepted(world)
    uploaded = await helpers.upload(
        world.employee,
        files.request_owner(request_helpers.rid(accepted)),
        helpers.fake_jpeg(),
        slot="overview",
    )
    await helpers.process()
    with pytest.raises(NotFound):
        await files.open_attachment(world.manager, helpers.aid(uploaded.body))


async def test_integration_key_needs_read_scope(world: World) -> None:
    _, private_id, _ = await _accepted_with_photos(world)
    narrow = IntegrationActor(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.integration.organization_id,
        scopes=frozenset({"events:read"}),
    )
    with pytest.raises(NotFound):
        await files.open_attachment(narrow, helpers.aid({"id": private_id}))


async def test_request_view_lists_only_allowed_attachments(world: World) -> None:
    accepted, private_id, sensitive_id = await _accepted_with_photos(world)
    request_id = request_helpers.rid(accepted)

    customer_view = await requests_api.get_request(world.manager, request_id)
    assert {item.id for item in customer_view.attachments} == {private_id, sensitive_id}

    provider_view = await requests_api.get_request(world.dispatcher, request_id)
    assert {item.id for item in provider_view.attachments} == {private_id, sensitive_id}
