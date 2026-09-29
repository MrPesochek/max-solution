import pytest

from app.core import ids
from app.core.errors import NotFound
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import factories
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_attach_only_to_own_message(world: World) -> None:
    accepted = await request_helpers.make_marketplace_accepted(world)
    request_id = request_helpers.rid(accepted)
    customer_message = (
        await requests_api.post_message(world.manager, request_id, body="Фото шильдика")
    ).body
    provider_message = (
        await requests_api.post_message(
            world.dispatcher,
            request_id,
            body="Фото узла",
            assignment_id=request_helpers.assignment_id(accepted),
        )
    ).body

    for actor, message in (
        (world.dispatcher, customer_message),
        (world.provider_admin, provider_message),
        (world.employee, customer_message),
    ):
        with pytest.raises(NotFound):
            await helpers.upload(
                actor, files.message_owner(ids.decode("message", message["id"])), helpers.png()
            )

    own = await helpers.upload(
        world.dispatcher,
        files.message_owner(ids.decode("message", provider_message["id"])),
        helpers.png(),
    )
    assert own.status == 201


async def test_new_provider_does_not_read_former_attachments(world: World) -> None:
    rival = await factories.build_rival_provider(world)
    accepted = await request_helpers.make_marketplace_accepted(world)
    request_id = request_helpers.rid(accepted)
    message = (
        await requests_api.post_message(
            world.dispatcher,
            request_id,
            body="Фото щитка",
            assignment_id=request_helpers.assignment_id(accepted),
        )
    ).body
    in_message = await helpers.upload(
        world.dispatcher, files.message_owner(ids.decode("message", message["id"])), helpers.png()
    )
    report = await helpers.upload(
        world.dispatcher, files.request_owner(request_id), helpers.png(), slot="before"
    )
    customer = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.png(), slot="overview"
    )
    await helpers.process()

    await request_helpers.change_provider_and_republish(world, accepted)
    selected = await request_helpers.select_next_provider(world, rival, request_id)
    await requests_api.accept_assignment(
        rival.dispatcher,
        request_id,
        assignment_id=request_helpers.assignment_id(selected),
        expected_version=selected["version"],
    )

    visible = {a.id for a in await files.list_for_request(rival.dispatcher, request_id)}
    assert visible == {customer.body["id"]}
    for hidden in (in_message, report):
        with pytest.raises(NotFound):
            await files.open_attachment(rival.dispatcher, helpers.aid(hidden.body))

    for_customer = {a.id for a in await files.list_for_request(world.manager, request_id)}
    assert for_customer == {in_message.body["id"], report.body["id"], customer.body["id"]}
