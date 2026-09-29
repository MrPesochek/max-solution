import pytest
from sqlalchemy import update

from app.core.errors import Conflict
from app.db import session as db_session
from app.db.models import ProviderProfile
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _set_status(world: World, status: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.organization_id == world.provider_org_id)
            .values(status=status)
        )


@pytest.mark.parametrize("status", ["suspended", "rejected"])
async def test_message_in_accepted_assignment_is_allowed(world: World, status: str) -> None:
    accepted = await h.make_accepted(world)
    await _set_status(world, status)
    for actor in (world.dispatcher, world.integration):
        posted = await api.post_message(
            actor,
            h.rid(accepted),
            body="Мастер будет завтра",
            assignment_id=h.assignment_id(accepted),
        )
        assert posted.status == 201


async def test_message_in_pending_assignment_is_blocked(world: World) -> None:
    submitted = await h.make_submitted(world)
    await _set_status(world, "suspended")
    for actor in (world.dispatcher, world.integration):
        with pytest.raises(Conflict) as exc:
            await api.post_message(
                actor,
                h.rid(submitted),
                body="Уточните адрес",
                assignment_id=h.assignment_id(submitted),
            )
        assert exc.value.code == "PROVIDER_NOT_ACTIVE"


async def test_active_provider_writes_in_pending_assignment(world: World) -> None:
    submitted = await h.make_submitted(world)
    posted = await api.post_message(
        world.dispatcher,
        h.rid(submitted),
        body="Уточните адрес",
        assignment_id=h.assignment_id(submitted),
    )
    assert posted.status == 201
