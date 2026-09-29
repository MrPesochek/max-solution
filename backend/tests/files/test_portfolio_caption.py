import uuid

import pytest

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.db.enums import ModerationStatus
from app.modules.files import api as files
from app.modules.providers import api as providers
from tests import support
from tests.files import helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _published_image(world: World) -> uuid.UUID:
    result = await files.submit_portfolio_image(
        world.provider_admin, stream=helpers.stream_of(helpers.png())
    )
    await helpers.process()
    attachment_id = helpers.aid(result.body)
    operator = await support.make_operator(f"cap-{attachment_id.hex[:6]}")
    await files.approve_attachment(operator, attachment_id)
    return attachment_id


async def test_caption_goes_to_moderation_with_photo(world: World) -> None:
    attachment_id = await _published_image(world)
    result = await files.set_portfolio_caption(
        world.provider_admin, attachment_id, "  Замена компрессора  "
    )
    assert result.body["caption"] == "Замена компрессора"
    assert await helpers.publication_state(attachment_id) == ModerationStatus.PENDING
    profile = await providers.get_public_profile(world.provider_org_id)
    assert profile.gallery_items == []

    operator = await support.make_operator("cap-approve")
    await files.approve_attachment(operator, attachment_id)
    profile = await providers.get_public_profile(world.provider_org_id)
    assert [(i.caption) for i in profile.gallery_items] == ["Замена компрессора"]

    listed = await files.list_portfolio(world.provider_admin)
    assert listed[0].caption == "Замена компрессора"


async def test_caption_rights_and_length(world: World, other_world: World) -> None:
    attachment_id = await _published_image(world)
    with pytest.raises(Forbidden):
        await files.set_portfolio_caption(world.dispatcher, attachment_id, "Подпись")
    with pytest.raises(NotFound):
        await files.set_portfolio_caption(other_world.provider_admin, attachment_id, "Чужое")
    with pytest.raises(ValidationFailed):
        await files.set_portfolio_caption(world.provider_admin, attachment_id, "x" * 201)
    await files.set_portfolio_caption(world.provider_admin, attachment_id, None)
    assert await helpers.publication_state(attachment_id) == ModerationStatus.PUBLISHED
