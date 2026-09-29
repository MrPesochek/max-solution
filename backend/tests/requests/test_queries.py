import pytest

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_customer_list_filters(world: World) -> None:
    closed_flow = await h.make_completion_reported(world)
    await api.confirm_completion(
        world.manager, h.rid(closed_flow), expected_version=closed_flow["version"]
    )
    fresh = await h.make_submitted(world)
    await api.create_draft(world.other_employee, equipment_id=world.other_equipment_id)

    active, _ = await api.list_requests(world.manager, active=True)
    assert {item.status for item in active} == {"awaiting_provider", "draft"}

    finished, _ = await api.list_requests(world.manager, active=False)
    assert [item.status for item in finished] == ["closed"]

    by_location, _ = await api.list_requests(world.manager, location_id=world.location_id)
    assert all(item.location_id == fresh["location"]["id"] for item in by_location)

    by_status, _ = await api.list_requests(world.manager, statuses=["awaiting_provider"])
    assert [item.id for item in by_status] == [fresh["id"]]
    assert by_status[0].assignment_state == "pending"
    assert by_status[0].equipment_title == "Полюс ВХС-1"


async def test_provider_list_buckets(world: World) -> None:
    incoming = await h.make_submitted(world)
    working = await h.make_accepted(world)

    pending, _ = await api.list_requests(world.dispatcher, assignment_states=["pending"])
    assert [item.id for item in pending] == [incoming["id"]]

    in_work, _ = await api.list_requests(world.integration, assignment_states=["accepted"])
    assert [item.id for item in in_work] == [working["id"]]

    everything, _ = await api.list_requests(world.dispatcher)
    assert len(everything) == 2


async def test_cursor_pagination(world: World) -> None:
    created = [await h.make_draft(world) for _ in range(3)]
    first, cursor = await api.list_requests(world.employee, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, tail = await api.list_requests(world.employee, limit=2, cursor=cursor)
    assert len(second) == 1
    assert tail is None
    assert {item.id for item in first + second} == {item["id"] for item in created}

    with pytest.raises(ValidationFailed):
        await api.list_requests(world.employee, limit=1000)
    with pytest.raises(ValidationFailed):
        await api.list_requests(world.employee, cursor="не-курсор")


async def test_history_pagination(world: World) -> None:
    accepted = await h.make_accepted(world)
    page, cursor = await api.request_history(world.manager, h.rid(accepted), limit=2)
    assert [event.event_type for event in page] == [
        "RequestDrafted",
        "RequestSubmittedToOwnService",
    ]
    rest, tail = await api.request_history(world.manager, h.rid(accepted), cursor=cursor)
    assert [event.event_type for event in rest] == ["AssignmentAccepted"]
    assert tail is None


async def test_employee_draft_goes_through_approval(world: World) -> None:
    draft = (
        await api.create_draft(world.employee, equipment_id=world.equipment_id, route="marketplace")
    ).body
    on_approval = (
        await api.request_approval(
            world.employee,
            h.rid(draft),
            comment="Нужен внешний мастер",
            expected_version=draft["version"],
        )
    ).body
    assert on_approval["status"] == "approval_required"
    assert (await h.notification_types()) == ["request.approval_required"]

    with pytest.raises(Forbidden):
        await api.return_to_draft(world.employee, h.rid(draft), comment="нет")

    back = (
        await api.return_to_draft(
            world.manager,
            h.rid(draft),
            comment="Добавьте фото",
            expected_version=on_approval["version"],
        )
    ).body
    assert back["status"] == "draft"

    again = (
        await api.request_approval(world.employee, h.rid(draft), expected_version=back["version"])
    ).body
    sent = (
        await api.submit_to_own_service(
            world.manager, h.rid(draft), expected_version=again["version"]
        )
    ).body
    assert sent["status"] == "awaiting_provider"
    assert sent["route"] == "own_service"


async def test_approval_requires_external_route(world: World) -> None:
    draft = await h.make_draft(world)
    with pytest.raises(Conflict) as exc:
        await api.request_approval(world.employee, h.rid(draft))
    assert exc.value.code == "INVALID_ROUTE"


async def test_completed_provider_still_reads_its_request(world: World) -> None:
    reported = await h.make_completion_reported(world)
    closed = (
        await api.confirm_completion(
            world.manager, h.rid(reported), expected_version=reported["version"]
        )
    ).body
    view = await api.get_request(world.dispatcher, h.rid(closed))
    assert view.assignment.state == "completed"
    messages, _ = await api.list_messages(world.dispatcher, h.rid(closed))
    assert messages == []
