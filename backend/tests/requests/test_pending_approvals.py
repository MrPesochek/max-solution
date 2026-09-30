from datetime import datetime
from typing import Any

import pytest

from app.core.errors import Forbidden
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _make_marketplace_draft(world: World) -> dict[str, Any]:
    result = await api.create_draft(
        world.employee, equipment_id=world.equipment_id, route="marketplace"
    )
    return result.body


async def test_aggregates_every_kind_for_manager(world: World) -> None:
    draft = await _make_marketplace_draft(world)
    await api.request_approval(world.employee, h.rid(draft), expected_version=draft["version"])

    submitted = await h.make_submitted(world)
    await api.decline_assignment(
        world.dispatcher,
        h.rid(submitted),
        assignment_id=h.assignment_id(submitted),
        reason="Нет запчасти",
        expected_version=submitted["version"],
    )

    accepted = await h.make_accepted(world)
    await api.propose_visit(
        world.dispatcher,
        h.rid(accepted),
        assignment_id=h.assignment_id(accepted),
        data=api.VisitProposalInput(**h.visit_window(), amount_minor=250000, currency="RUB"),
        expected_version=accepted["version"],
    )

    accepted_2 = await h.make_accepted(world)
    await api.create_repair_quote(
        world.dispatcher,
        h.rid(accepted_2),
        assignment_id=h.assignment_id(accepted_2),
        data=api.RepairQuoteInput(
            description_of_work="Замена компрессора", amount_minor=500000, currency="RUB"
        ),
        expected_version=accepted_2["version"],
    )

    await h.make_completion_reported(world)

    scheduled = await h.make_scheduled(world)
    pending_cancellation = (
        await api.request_cancellation(
            world.manager,
            h.rid(scheduled),
            target="cancel_request",
            reason="Нашли другого",
            expected_version=scheduled["version"],
        )
    ).body
    await api.respond_cancellation(
        world.dispatcher,
        h.rid(pending_cancellation),
        assignment_id=h.assignment_id(pending_cancellation),
        cancellation_id=h.cancellation_id(pending_cancellation),
        decision="decline",
        comment="Мастер уже выехал",
        expected_version=pending_cancellation["version"],
    )

    items = await api.pending_approvals(world.manager)
    kinds = {item.kind for item in items}
    assert kinds == {
        "draft_approval",
        "action_required",
        "visit_proposal",
        "repair_quote",
        "completion_reported",
        "cancellation_disputed",
    }

    by_kind = {item.kind: item for item in items}
    assert by_kind["visit_proposal"].object is not None
    assert by_kind["visit_proposal"].object.version == 1
    assert by_kind["visit_proposal"].due_at is not None
    assert by_kind["repair_quote"].object is not None
    assert by_kind["cancellation_disputed"].due_at is not None
    assert by_kind["draft_approval"].request.status == "approval_required"
    assert by_kind["completion_reported"].request.status == "completion_reported"
    assert by_kind["action_required"].request.status == "action_required"


async def test_employee_gets_no_manager_decisions(world: World) -> None:
    draft = await _make_marketplace_draft(world)
    await api.request_approval(world.employee, h.rid(draft), expected_version=draft["version"])
    assert await api.pending_approvals(world.employee) == []


async def test_provider_is_forbidden(world: World) -> None:
    with pytest.raises(Forbidden):
        await api.pending_approvals(world.dispatcher)


async def test_ignores_other_organization(world: World, other_world: World) -> None:
    draft = await _make_marketplace_draft(other_world)
    await api.request_approval(
        other_world.employee, h.rid(draft), expected_version=draft["version"]
    )

    items = await api.pending_approvals(world.manager)
    assert items == []


async def test_expired_proposal_and_quote_are_excluded(world: World, clock: Clock) -> None:
    accepted = await h.make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=250000, currency="RUB"),
            expected_version=accepted["version"],
        )
    ).body
    valid_until = proposed["visit_proposals"][0]["valid_until"]
    clock.now = datetime.fromisoformat(valid_until) + h.hours(1)

    items = await api.pending_approvals(world.manager)
    assert all(item.kind != "visit_proposal" for item in items)
