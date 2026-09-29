import uuid

import pytest

from app.core.errors import NotFound
from app.db import session as db_session
from app.db.models import Organization
from app.modules.requests import api, recipients
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _customer_side_member(world: World) -> tuple[uuid.UUID, uuid.UUID]:
    """Руководитель заказчика в организации-исполнителе и его же роль диспетчера."""
    async with db_session.transaction() as session:
        provider = await session.get(Organization, world.provider_org_id)
        assert provider is not None
        provider.is_customer = True
        user = await factories.create_user(session, "Двойная роль")
        customer_side = await factories.create_membership(
            session, user, provider, "customer_manager"
        )
        provider_side = await factories.create_membership(
            session, user, provider, "provider_dispatcher"
        )
        return customer_side.id, provider_side.id


async def test_customer_side_membership_is_not_a_field_worker(world: World) -> None:
    customer_side, provider_side = await _customer_side_member(world)
    accepted = await h.make_accepted(world)

    with pytest.raises(NotFound):
        await api.set_field_worker(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            membership_id=customer_side,
            display_name=None,
            contact_phone=None,
            expected_version=accepted["version"],
        )
    assigned = (
        await api.set_field_worker(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            membership_id=provider_side,
            display_name=None,
            contact_phone=None,
            expected_version=accepted["version"],
        )
    ).body
    assert assigned["assignment"]["field_worker"]["display_name"] == "Двойная роль"
    assert assigned["assignment"]["field_worker"]["stated_by_company"] is False
    for actor in (world.dispatcher, world.manager):
        card = await api.get_request(actor, h.rid(accepted))
        assert card.assignment.field_worker.display_name == "Двойная роль"


async def test_provider_recipients_skip_customer_side(world: World) -> None:
    customer_side, provider_side = await _customer_side_member(world)
    async with db_session.transaction() as session:
        targets = await recipients.provider_org_targets(
            session,
            world.provider_org_id,
            field_worker_membership_id=customer_side,
        )
    memberships = {t.membership_id for t in targets}
    assert customer_side not in memberships
    assert provider_side in memberships
