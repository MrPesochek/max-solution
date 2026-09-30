from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.pipeline import CommandContext, CommandResult, run_command
from app.db import session as db_session
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import factories as request_factories
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest_asyncio.fixture
async def single_connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_engine.url, pool_size=1, max_overflow=0, pool_timeout=1)
    db_session.configure(engine)
    try:
        yield engine
    finally:
        db_session.configure(db_engine)
        await engine.dispose()


async def _draft_with_photo(world: World) -> tuple[dict, object]:
    draft = await request_helpers.make_marketplace_draft(world)
    request_id = request_helpers.rid(draft)
    photo = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="overview"
    )
    await helpers.process()
    return draft, helpers.aid(photo.body)


async def test_publish_card_and_reads_fit_one_connection(
    world: World, single_connection: AsyncEngine
) -> None:
    rival = await request_factories.build_rival_provider(world)
    draft, photo_id = await _draft_with_photo(world)
    request_id = request_helpers.rid(draft)

    published = await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(attachment_ids=(photo_id,)),
        expected_version=draft["version"],
    )
    assert published.body["status"] == "searching"
    assert [a["id"] for a in published.body["attachments"]] != []
    assert len(published.body["search"]["public_card"]["published_attachment_ids"]) == 1

    card = await requests_api.get_request(world.manager, request_id)
    assert len(card.attachments) == len(published.body["attachments"])

    copy_id = (await request_helpers.public_card(published.body)).published_attachment_ids[0]
    assert await helpers.read_content(rival.dispatcher, copy_id)
    assert (await files.get_attachment(rival.dispatcher, copy_id)).id


async def test_provider_command_fits_one_connection(
    world: World, single_connection: AsyncEngine
) -> None:
    submitted = await request_helpers.make_submitted(world)
    accepted = await requests_api.accept_assignment(
        world.dispatcher,
        request_helpers.rid(submitted),
        assignment_id=request_helpers.assignment_id(submitted),
        expected_version=submitted["version"],
    )
    assert accepted.body["assignment"]["state"] == "accepted"
    card = await requests_api.get_request(world.dispatcher, request_helpers.rid(submitted))
    assert card.assignment.state == "accepted"
    items, _ = await requests_api.list_requests(world.dispatcher)
    assert len(items) == 1


async def test_second_connection_inside_command_is_detected(
    world: World, single_connection: AsyncEngine
) -> None:
    draft = await request_helpers.make_marketplace_draft(world)

    async def handler(ctx: CommandContext) -> CommandResult:
        await ctx.session.execute(text("SELECT 1"))
        await files.list_for_request(ctx.actor, request_helpers.rid(draft))
        return CommandResult({})

    with pytest.raises(sa_exc.TimeoutError):
        await run_command(world.manager, handler)
