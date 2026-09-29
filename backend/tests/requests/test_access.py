import uuid

import pytest

from app.core.actor import IntegrationActor
from app.core.errors import Forbidden, NotFound
from app.db.models import Assignment
from app.modules.requests import api, policy
from app.modules.requests.views import RequestCustomerView, RequestProviderView
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_employee_sees_only_own_locations(world: World) -> None:
    mine = await h.make_draft(world)
    theirs = (
        await api.create_draft(world.other_employee, equipment_id=world.other_equipment_id)
    ).body

    with pytest.raises(NotFound):
        await api.get_request(world.employee, h.rid(theirs))
    with pytest.raises(NotFound):
        await api.create_draft(world.employee, equipment_id=world.other_equipment_id)

    items, _ = await api.list_requests(world.employee)
    assert [item.id for item in items] == [mine["id"]]

    manager_items, _ = await api.list_requests(world.manager)
    assert {item.id for item in manager_items} == {mine["id"], theirs["id"]}


async def test_employee_cannot_approve_or_close(world: World) -> None:
    reported = await h.make_completion_reported(world)
    request_id = h.rid(reported)
    for call in (
        api.confirm_completion(world.employee, request_id),
        api.reject_completion(world.employee, request_id, reason="Плохо"),
        api.return_to_draft(world.employee, request_id, comment="Верни"),
        api.force_cancellation(world.employee, request_id, cancellation_id=uuid.uuid4()),
    ):
        with pytest.raises(Forbidden):
            await call


async def test_integration_client_cannot_act_for_customer(world: World) -> None:
    reported = await h.make_completion_reported(world)
    request_id = h.rid(reported)
    with pytest.raises(Forbidden):
        await api.confirm_completion(world.integration, request_id)
    with pytest.raises(Forbidden):
        await api.approve_visit_proposal(
            world.integration, request_id, proposal_id=uuid.uuid4(), proposal_version=1
        )
    with pytest.raises(Forbidden):
        await api.create_draft(world.integration, equipment_id=world.equipment_id)


async def test_integration_client_needs_scope(world: World) -> None:
    submitted = await h.make_submitted(world)
    readonly = IntegrationActor(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.provider_org_id,
        scopes=frozenset({"requests:read"}),
    )
    with pytest.raises(Forbidden) as exc:
        await api.accept_assignment(
            readonly, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )
    assert exc.value.code == "INSUFFICIENT_SCOPE"

    view = await api.get_request(readonly, h.rid(submitted))
    assert isinstance(view, RequestProviderView)

    blind = IntegrationActor(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.provider_org_id,
        scopes=frozenset(),
    )
    with pytest.raises(Forbidden):
        await api.get_request(blind, h.rid(submitted))


async def test_provider_user_cannot_use_customer_commands(world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(Forbidden):
        await api.confirm_completion(world.dispatcher, h.rid(accepted))
    with pytest.raises(Forbidden):
        await api.update_draft(world.dispatcher, h.rid(accepted), urgency="urgent")


async def test_own_service_provider_sees_address_before_answer(world: World) -> None:
    submitted = await h.make_submitted(world)
    view = await api.get_request(world.dispatcher, h.rid(submitted))
    assert isinstance(view, RequestProviderView)
    assert view.contacts_disclosed is True
    assert view.location.address == "ул. Примерная, 1"


def test_marketplace_pending_hides_contacts() -> None:
    """ТЗ 11: `offer.selected` ещё не раскрывает точный адрес."""
    reserved = Assignment(
        request_id=uuid.uuid4(),
        provider_org_id=uuid.uuid4(),
        route="marketplace",
        state="pending",
    )
    assert policy.discloses_contacts(reserved) is False
    reserved.state = "accepted"
    assert policy.discloses_contacts(reserved) is True


async def test_customer_view_keeps_full_card(world: World) -> None:
    accepted = await h.make_accepted(world)
    view = await api.get_request(world.manager, h.rid(accepted))
    assert isinstance(view, RequestCustomerView)
    assert view.equipment.serial_number == "SN-0001"
    assert view.location.contact_phone == "+70000000000"
    assert view.assignment is not None
    assert view.assignment.provider_display_name == "Холод-Сервис"


async def test_unknown_request_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        await api.get_request(world.manager, uuid.uuid4())
    with pytest.raises(NotFound):
        await api.list_messages(world.dispatcher, uuid.uuid4())
