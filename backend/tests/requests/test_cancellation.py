import pytest

from app.core.actor import UserActor
from app.core.errors import Conflict, Forbidden
from app.db import session as db_session
from app.db.enums import AssignmentState, CancellationStatus, VisitProposalStatus
from app.db.models import (
    Assignment,
    CancellationRequest,
    Organization,
    RepairRequest,
    VisitProposal,
)
from app.modules.requests import api
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_a15_cancel_before_acceptance_is_immediate(world: World) -> None:
    submitted = await h.make_submitted(world)
    cancelled = (
        await api.request_cancellation(
            world.manager,
            h.rid(submitted),
            target="cancel_request",
            reason="Оборудование заменили",
            expected_version=submitted["version"],
        )
    ).body
    assert cancelled["status"] == "cancelled"
    assert cancelled["assignment"]["state"] == "revoked"
    assert cancelled["cancelled_at"] is not None
    assert await h.count_of(CancellationRequest) == 0
    assert (await h.event_types())[-1] == "assignment.revoked"


async def test_a15_cancel_after_acceptance_needs_answer(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager,
            h.rid(accepted),
            target="cancel_request",
            reason="Закрываем точку",
            expected_version=accepted["version"],
        )
    ).body
    assert pending["status"] == "cancellation_pending"
    assert pending["cancellation"]["previous_status"] == "accepted"

    with pytest.raises(Conflict) as exc:
        await api.request_cancellation(
            world.manager, h.rid(pending), target="cancel_request", reason="Ещё раз"
        )
    assert exc.value.code == "CANCELLATION_ALREADY_OPEN"

    done = (
        await api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
            expected_version=pending["version"],
        )
    ).body
    assert done["status"] == "cancelled"
    row = await h.reload(CancellationRequest, h.cancellation_id(pending))
    assert row.status == CancellationStatus.ACCEPTED
    assert row.resolution_kind == "provider_confirmed"


async def test_employee_cannot_cancel_accepted_request(world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(Forbidden):
        await api.request_cancellation(
            world.employee, h.rid(accepted), target="cancel_request", reason="Не нужно"
        )


async def test_dispute_restores_previous_status_and_unblocks_after_deadline(
    world: World, clock: Clock
) -> None:
    scheduled = await h.make_scheduled(world)
    pending = (
        await api.request_cancellation(
            world.manager,
            h.rid(scheduled),
            target="cancel_request",
            reason="Нашли другого",
            expected_version=scheduled["version"],
        )
    ).body

    disputed = (
        await api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="decline",
            comment="Мастер уже выехал",
            expected_version=pending["version"],
        )
    ).body
    assert disputed["status"] == "scheduled"
    assert disputed["cancellation"]["status"] == "disputed"
    assert disputed["cancellation"]["dispute_deadline_at"] is not None

    with pytest.raises(Conflict) as exc:
        await api.force_cancellation(
            world.manager, h.rid(pending), cancellation_id=h.cancellation_id(pending)
        )
    assert exc.value.code == "DISPUTE_PERIOD_ACTIVE"

    clock.advance(hours=73)
    forced = (
        await api.force_cancellation(
            world.manager,
            h.rid(pending),
            cancellation_id=h.cancellation_id(pending),
            expected_version=disputed["version"],
        )
    ).body
    assert forced["status"] == "cancelled"
    assert forced["disputed"] is True
    assert forced["cancellation"]["status"] == "force_closed"
    assert forced["cancellation"]["resolution_kind"] == "customer_unilateral"

    assignment = await h.reload(Assignment, h.assignment_id(pending))
    assert assignment.state == AssignmentState.REVOKED
    proposals = await api.list_visit_proposals(world.manager, h.rid(pending))
    assert proposals[0]["status"] == VisitProposalStatus.SUPERSEDED
    assert (await h.event_types())[-1] == "assignment.revoked"


async def test_withdrawn_cancellation_returns_request(world: World) -> None:
    in_progress = await h.make_in_progress(world)
    pending = (
        await api.request_cancellation(
            world.manager,
            h.rid(in_progress),
            target="change_provider",
            reason="Долго",
            expected_version=in_progress["version"],
        )
    ).body
    restored = (
        await api.withdraw_cancellation(
            world.manager,
            h.rid(pending),
            cancellation_id=h.cancellation_id(pending),
            expected_version=pending["version"],
        )
    ).body
    assert restored["status"] == "in_progress"
    assert restored["cancellation"]["status"] == "withdrawn"


async def test_withdraw_after_dispute_keeps_working_status(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Передумали"
        )
    ).body
    disputed = (
        await api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="decline",
            comment="Работа начата",
        )
    ).body
    assert disputed["status"] == "accepted"

    closed = (
        await api.withdraw_cancellation(
            world.manager,
            h.rid(pending),
            cancellation_id=h.cancellation_id(pending),
            expected_version=disputed["version"],
        )
    ).body
    assert closed["status"] == "accepted"
    assert closed["cancellation"]["status"] == "withdrawn"


async def test_cancel_draft_only_by_author_or_manager(world: World) -> None:
    draft = await h.make_draft(world)
    colleague = await _colleague(world)
    with pytest.raises(Forbidden):
        await api.cancel_draft(colleague, h.rid(draft))

    cancelled = (
        await api.cancel_draft(
            world.manager, h.rid(draft), reason="Не требуется", expected_version=draft["version"]
        )
    ).body
    assert cancelled["status"] == "cancelled"


async def _colleague(world: World) -> UserActor:
    """Второй сотрудник той же точки — не автор черновика."""
    async with db_session.transaction() as session:
        org = await session.get(Organization, world.customer_org_id)
        assert org is not None
        user = await factories.create_user(session, "Второй сотрудник")
        membership = await factories.create_membership(
            session, user, org, "customer_employee", location_ids=(world.location_id,)
        )
        return UserActor(
            user_id=user.id,
            membership_id=membership.id,
            organization_id=org.id,
            role="customer_employee",
            location_ids=frozenset({world.location_id}),
        )


async def test_terminal_request_rejects_changes(world: World) -> None:
    reported = await h.make_completion_reported(world)
    closed = (
        await api.confirm_completion(
            world.manager, h.rid(reported), expected_version=reported["version"]
        )
    ).body
    with pytest.raises(Conflict):
        await api.post_message(world.employee, h.rid(closed), body="Ещё вопрос")
    with pytest.raises(Conflict):
        await api.request_cancellation(
            world.manager, h.rid(closed), target="cancel_request", reason="Поздно"
        )
    assert await h.count_of(RepairRequest) == 1
    assert await h.count_of(VisitProposal) == 1


async def test_request_cancellable_again_after_withdrawal(world: World) -> None:
    """Отозванный запрос остаётся в карточке историей и не мешает новому (S6/A15)."""
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Передумали"
        )
    ).body
    await api.withdraw_cancellation(
        world.manager, h.rid(pending), cancellation_id=h.cancellation_id(pending)
    )
    card = await api.get_request(world.manager, h.rid(accepted))
    assert card.status == "accepted"
    assert card.cancellation is not None
    assert card.cancellation.status == "withdrawn"

    again = (
        await api.request_cancellation(
            world.manager,
            h.rid(accepted),
            target="cancel_request",
            reason="Всё-таки отменяем",
            expected_version=card.version,
        )
    ).body
    assert again["status"] == "cancellation_pending"
    assert again["cancellation"]["status"] == "pending"
    assert h.cancellation_id(again) != h.cancellation_id(pending)


async def test_disputed_cancellation_stays_in_card_and_blocks_new_one(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Передумали"
        )
    ).body
    await api.respond_cancellation(
        world.dispatcher,
        h.rid(pending),
        assignment_id=h.assignment_id(pending),
        cancellation_id=h.cancellation_id(pending),
        decision="decline",
        comment="Работа начата",
    )
    card = await api.get_request(world.manager, h.rid(accepted))
    assert card.status == "accepted"
    assert card.cancellation is not None
    assert card.cancellation.status == "disputed"

    with pytest.raises(Conflict) as exc:
        await api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Ещё раз"
        )
    assert exc.value.code == "CANCELLATION_ALREADY_OPEN"
