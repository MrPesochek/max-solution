import uuid
from typing import Any

import pytest

from app.core import ids
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
    first = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="overview"
    )
    second = await helpers.upload(
        world.manager, files.request_owner(request_id), helpers.jpeg_with_gps(), slot="nameplate"
    )
    await helpers.process()
    return draft, helpers.aid(first.body), helpers.aid(second.body)


async def test_customer_card_names_source_photos_of_last_publication(world: World) -> None:
    await request_factories.build_rival_provider(world)
    draft, first_id, second_id = await _draft_with_photos(world)
    request_id = request_helpers.rid(draft)

    published = await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(attachment_ids=(first_id,)),
        expected_version=draft["version"],
    )
    card = (await requests_api.get_request(world.manager, request_id)).model_dump(mode="json")
    search = card["search"]
    assert search["published_source_attachment_ids"] == [ids.encode("attachment", first_id)]
    assert search["public_card"]["published_attachment_ids"] != [ids.encode("attachment", first_id)]
    assert ids.encode("attachment", second_id) not in search["published_source_attachment_ids"]

    await requests_api.request_cancellation(
        world.manager,
        request_id,
        target="change_provider",
        reason=None,
        expected_version=published.body["version"],
    )
    stopped = (await requests_api.get_request(world.manager, request_id)).model_dump(mode="json")
    assert stopped["status"] == "action_required"
    assert stopped["search"]["published"] is False
    assert stopped["search"]["public_card"]["published_attachment_ids"] == []
    assert stopped["search"]["published_source_attachment_ids"] == [
        ids.encode("attachment", first_id)
    ]


async def test_publication_without_photos_has_no_sources(world: World) -> None:
    await request_factories.build_rival_provider(world)
    draft, _, _ = await _draft_with_photos(world)
    request_id = request_helpers.rid(draft)

    await requests_api.publish_search(
        world.manager,
        request_id,
        data=requests_api.PublicCardInput(attachment_ids=()),
        expected_version=draft["version"],
    )
    card = (await requests_api.get_request(world.manager, request_id)).model_dump(mode="json")
    assert card["search"]["published_source_attachment_ids"] == []
