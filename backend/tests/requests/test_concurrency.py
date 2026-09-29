import asyncio
from typing import Any

import pytest

from app.core.errors import DomainError
from app.core.pipeline import Idempotency, hash_body
from app.db.enums import AssignmentState
from app.db.models import Assignment, IntegrationEvent, RepairRequest, RequestEvent, VisitProposal
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str, payload: dict[str, Any] | None = None) -> Idempotency:
    return Idempotency(key=key, operation="requests.test", body_hash=hash_body(payload or {}))


def _outcomes(results: list[Any]) -> tuple[int, list[str]]:
    ok = sum(1 for r in results if not isinstance(r, BaseException))
    codes = [r.code for r in results if isinstance(r, DomainError)]
    assert not [
        r for r in results if isinstance(r, BaseException) and not isinstance(r, DomainError)
    ]
    return ok, codes


async def test_a09_accept_and_revoke_race(world: World) -> None:
    submitted = await h.make_submitted(world)
    request_id = h.rid(submitted)
    assignment = h.assignment_id(submitted)

    results = await asyncio.gather(
        api.accept_assignment(world.dispatcher, request_id, assignment_id=assignment),
        api.revoke_pending_assignment(world.manager, request_id, assignment_id=assignment),
        return_exceptions=True,
    )
    ok, codes = _outcomes(list(results))
    assert ok == 1
    assert codes and codes[0] in {"ASSIGNMENT_NOT_ACTIVE", "INVALID_TRANSITION"}

    row = await h.reload(Assignment, assignment)
    assert row.state in {AssignmentState.ACCEPTED, AssignmentState.REVOKED}
    assert await h.count_of(Assignment) == 1


async def test_a09_two_submissions_do_not_create_two_assignments(world: World) -> None:
    draft = await h.make_draft(world)
    request_id = h.rid(draft)
    results = await asyncio.gather(
        api.submit_to_own_service(world.employee, request_id),
        api.submit_to_own_service(world.manager, request_id),
        return_exceptions=True,
    )
    ok, _ = _outcomes(list(results))
    assert ok == 1
    assert await h.count_of(Assignment) == 1


async def test_parallel_approvals_apply_once(world: World) -> None:
    accepted = await h.make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=120000, currency="RUB"),
            expected_version=accepted["version"],
        )
    ).body
    request_id = h.rid(proposed)
    proposal = h.proposal_id(proposed)

    results = await asyncio.gather(
        api.approve_visit_proposal(
            world.manager, request_id, proposal_id=proposal, proposal_version=1
        ),
        api.approve_visit_proposal(
            world.manager, request_id, proposal_id=proposal, proposal_version=1
        ),
        return_exceptions=True,
    )
    ok, codes = _outcomes(list(results))
    assert ok == 1
    assert codes == ["PROPOSAL_NOT_PENDING"]

    row = await h.reload(VisitProposal, proposal)
    assert row.status == "approved"
    request = await h.reload(RepairRequest, request_id)
    assert request.status == "scheduled"


async def test_a16_idempotent_replay(world: World) -> None:
    draft = await h.make_draft(world)
    key = _idem("submit-key-0001", {"request": str(h.rid(draft))})

    first = await api.submit_to_own_service(world.employee, h.rid(draft), idem=key)
    second = await api.submit_to_own_service(world.employee, h.rid(draft), idem=key)

    assert second.replayed is True
    assert second.body == first.body
    assert await h.count_of(Assignment) == 1
    assert await h.count_of(IntegrationEvent) == 1
    events = await h.notification_types()
    assert events.count("request.assigned") == 2


async def test_concurrent_same_idempotency_key_runs_once(world: World) -> None:
    draft = await h.make_draft(world)
    key = _idem("submit-key-0002", {"request": str(h.rid(draft))})
    results = await asyncio.gather(
        *[api.submit_to_own_service(world.employee, h.rid(draft), idem=key) for _ in range(4)],
        return_exceptions=True,
    )
    ok, _ = _outcomes(list(results))
    assert ok == 4
    assert await h.count_of(Assignment) == 1
    assert await h.count_of(RequestEvent) == 2
