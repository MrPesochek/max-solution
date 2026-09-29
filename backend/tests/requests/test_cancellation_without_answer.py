import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.db import session as db_session
from app.db.models import Assignment, AuditEntry, CancellationRequest
from app.modules.requests import api
from app.modules.requests.sweeper import expire_due
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _pending(world: World) -> dict[str, object]:
    scheduled = await h.make_scheduled(world)
    return (
        await api.request_cancellation(
            world.manager,
            h.rid(scheduled),
            target="cancel_request",
            reason="Закрываем точку",
            expected_version=scheduled["version"],
        )
    ).body


async def test_silent_provider_lets_manager_force_after_deadline(
    world: World, clock: Clock
) -> None:
    pending = await _pending(world)
    assert pending["cancellation"]["dispute_deadline_at"] is not None

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
            expected_version=pending["version"],
        )
    ).body
    assert forced["status"] == "cancelled"
    assert forced["cancellation"]["status"] == "force_closed"
    assert forced["cancellation"]["resolution_kind"] == "customer_unilateral"
    assert forced["cancellation"]["disputed"] is False
    assignment = await h.reload(Assignment, h.assignment_id(pending))
    assert assignment.state == "revoked"
    async with db_session.transaction() as session:
        details = (
            await session.execute(
                select(AuditEntry.details).where(AuditEntry.action == "ForceCancellation")
            )
        ).scalar_one()
    assert details["provider_silent"] is True


async def test_employee_still_cannot_force(world: World, clock: Clock) -> None:
    pending = await _pending(world)
    clock.advance(hours=73)
    with pytest.raises(Exception) as exc:
        await api.force_cancellation(
            world.employee, h.rid(pending), cancellation_id=h.cancellation_id(pending)
        )
    assert type(exc.value).__name__ in {"Forbidden", "NotFound"}


async def test_sweeper_reminds_both_sides_once_without_transition(
    world: World, clock: Clock
) -> None:
    pending = await _pending(world)
    assert (await expire_due())["cancellation_reminders"] == 0

    clock.advance(hours=73)
    assert (await expire_due())["cancellation_reminders"] == 1
    assert (await expire_due())["cancellation_reminders"] == 0

    types = await h.notification_types()
    assert types.count("cancellation.reminder") >= 1
    assert types.count("cancellation.no_response") == 1
    view = await api.get_request(world.manager, h.rid(pending))
    assert view.status == "cancellation_pending"
    row = await h.reload(CancellationRequest, h.cancellation_id(pending))
    assert row.reminded_at is not None


async def test_answered_cancellation_is_not_reminded(world: World, clock: Clock) -> None:
    pending = await _pending(world)
    await api.respond_cancellation(
        world.dispatcher,
        h.rid(pending),
        assignment_id=h.assignment_id(pending),
        cancellation_id=h.cancellation_id(pending),
        decision="decline",
        comment="Мастер уже выехал",
        expected_version=pending["version"],
    )
    clock.advance(hours=73)
    assert (await expire_due())["cancellation_reminders"] == 0
