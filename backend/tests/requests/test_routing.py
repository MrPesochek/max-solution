import pytest

from app.core.errors import Conflict, NotFound
from app.db.enums import AssignmentState
from app.db.models import Assignment
from app.modules.requests import api
from app.modules.requests.views import RequestFormerProviderView
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_decline_moves_request_to_action_required(world: World) -> None:
    submitted = await h.make_submitted(world)
    declined = (
        await api.decline_assignment(
            world.dispatcher,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            reason="Нет запчасти",
            expected_version=submitted["version"],
        )
    ).body
    assert declined["status"] == "action_required"
    assert declined["assignment"]["state"] == "declined"

    view = await api.get_request(world.manager, h.rid(submitted))
    assert view.status == "action_required"

    resubmitted = (
        await api.submit_to_own_service(
            world.manager, h.rid(submitted), expected_version=declined["version"]
        )
    ).body
    assert resubmitted["status"] == "awaiting_provider"
    assert h.assignment_id(resubmitted) != h.assignment_id(submitted)
    assert await h.count_of(Assignment) == 2


async def test_revoke_pending_assignment_and_late_answer(world: World) -> None:
    submitted = await h.make_submitted(world)
    revoked = (
        await api.revoke_pending_assignment(
            world.manager,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            reason="Договорились по телефону",
            expected_version=submitted["version"],
        )
    ).body
    assert revoked["status"] == "action_required"
    assert revoked["assignment"]["state"] == "revoked"

    with pytest.raises(Conflict) as exc:
        await api.accept_assignment(
            world.dispatcher, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )
    assert exc.value.code == "ASSIGNMENT_NOT_ACTIVE"


async def test_employee_cannot_revoke_assignment(world: World) -> None:
    submitted = await h.make_submitted(world)
    from app.core.errors import Forbidden

    with pytest.raises(Forbidden):
        await api.revoke_pending_assignment(
            world.employee, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )


async def test_former_provider_loses_access(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.post_message(world.employee, h.rid(accepted), body="Вопрос")
    withdrawn = (
        await api.withdraw_assignment(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            reason="Мастер заболел",
        )
    ).body
    assert withdrawn["status"] == "action_required"
    assert withdrawn["assignment"]["state"] == "withdrawn"

    view = await api.get_request(world.dispatcher, h.rid(accepted))
    assert isinstance(view, RequestFormerProviderView)
    assert view.assignment.state == "withdrawn"

    with pytest.raises(NotFound):
        await api.list_messages(world.dispatcher, h.rid(accepted))
    with pytest.raises(NotFound):
        await api.request_history(world.integration, h.rid(accepted))

    types = await h.event_types()
    assert types[-1] == "assignment.revoked"
    events = await h.integration_events()
    assert "request" not in events[-1].payload
    assert events[-1].payload["reason_kind"] == "provider_withdrawn"


async def test_change_provider_frees_the_slot(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager,
            h.rid(accepted),
            target="change_provider",
            reason="Нужен другой сервис",
            expected_version=accepted["version"],
        )
    ).body
    assert pending["status"] == "cancellation_pending"

    answered = (
        await api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
            expected_version=pending["version"],
        )
    ).body
    assert answered["status"] == "action_required"
    assert answered["assignment"]["state"] == "revoked"

    resubmitted = (
        await api.submit_to_own_service(
            world.manager, h.rid(accepted), expected_version=answered["version"]
        )
    ).body
    assert resubmitted["status"] == "awaiting_provider"
    assignments = await h.integration_events()
    assert assignments


async def test_provider_of_other_organization_is_not_found(
    world: World, other_world: World
) -> None:
    submitted = await h.make_submitted(world)
    with pytest.raises(NotFound):
        await api.accept_assignment(
            other_world.dispatcher, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )
    with pytest.raises(NotFound):
        await api.get_request(other_world.integration, h.rid(submitted))
    row = await h.reload(Assignment, h.assignment_id(submitted))
    assert row.state == AssignmentState.PENDING
