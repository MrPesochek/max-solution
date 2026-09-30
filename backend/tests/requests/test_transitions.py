import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import SystemActor
from app.core.errors import InvalidTransition
from app.core.pipeline import CommandContext
from app.db.enums import RequestStatus
from app.db.models import RepairRequest
from app.modules.requests.transitions import (
    INDEX,
    TRANSITIONS,
    Transition,
    apply_transition,
)

ALL_STATUSES = tuple(str(status) for status in RequestStatus)


class _CollectingSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _ctx() -> tuple[CommandContext, _CollectingSession]:
    session = _CollectingSession()
    ctx = CommandContext(
        session=cast(AsyncSession, session),
        actor=SystemActor(name="test"),
        now=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    return ctx, session


def _request(status: str) -> RepairRequest:
    request = RepairRequest(
        id=uuid.uuid4(),
        customer_org_id=uuid.uuid4(),
        location_id=uuid.uuid4(),
        equipment_id=uuid.uuid4(),
        author_membership_id=uuid.uuid4(),
        route="own_service",
        status=status,
        version=3,
        urgency="normal",
        equipment_snapshot={},
        location_snapshot={},
    )
    return request


def test_table_is_indexed_by_command_and_target() -> None:
    assert len(INDEX) == len(TRANSITIONS)
    assert len({(row.command, row.to_status) for row in TRANSITIONS}) == len(TRANSITIONS)


def _row_id(row: Transition) -> str:
    return f"{row.command}:{'|'.join(sorted(row.from_statuses))}"


@pytest.mark.parametrize("row", TRANSITIONS, ids=_row_id)
def test_allowed_transitions_apply(row: Transition) -> None:
    sources = row.from_statuses or {RequestStatus.DRAFT}
    for source in sources:
        ctx, session = _ctx()
        request = _request(str(source))
        before = request.version

        apply_transition(ctx, request, row.command, row.to_status)

        assert request.status == (row.to_status or source)
        bumps = not row.initial and row.versioned
        assert request.version == (before + 1 if bumps else before)
        event = session.added[-1]
        assert event.event_type == row.event_type
        assert event.from_status == (None if row.initial else str(source))
        assert event.to_status == row.to_status


@pytest.mark.parametrize(
    "row",
    [row for row in TRANSITIONS if not row.initial],
    ids=_row_id,
)
def test_forbidden_sources_are_rejected(row: Transition) -> None:
    for status in ALL_STATUSES:
        if status in row.from_statuses:
            continue
        ctx, _ = _ctx()
        request = _request(status)
        with pytest.raises(InvalidTransition) as exc:
            apply_transition(ctx, request, row.command, row.to_status)
        assert exc.value.details["status"] == status
        assert exc.value.code == "INVALID_TRANSITION"
        assert request.version == 3


def test_metric_timestamps_are_stamped_once() -> None:
    ctx, _ = _ctx()
    request = _request(RequestStatus.DRAFT)
    from app.modules.requests.transitions import RequestCommand as C

    apply_transition(ctx, request, C.SUBMIT_TO_OWN_SERVICE, RequestStatus.AWAITING_PROVIDER)
    first = request.submitted_at
    assert first == ctx.now
    assert request.accepted_at is None

    apply_transition(ctx, request, C.ACCEPT_REQUEST, RequestStatus.ACCEPTED)
    assert request.accepted_at == ctx.now

    apply_transition(ctx, request, C.REQUEST_CANCELLATION, RequestStatus.CANCELLATION_PENDING)
    apply_transition(ctx, request, C.DECLINE_CANCELLATION, RequestStatus.ACCEPTED)
    assert request.submitted_at == first


def test_messages_do_not_touch_aggregate_version() -> None:
    ctx, _ = _ctx()
    from app.modules.requests.transitions import RequestCommand as C

    request = _request(RequestStatus.ACCEPTED)
    apply_transition(ctx, request, C.POST_MESSAGE, None)
    assert request.version == 3


def test_unknown_pair_is_invalid_transition() -> None:
    ctx, _ = _ctx()
    from app.modules.requests.transitions import RequestCommand as C

    request = _request(RequestStatus.ACCEPTED)
    with pytest.raises(InvalidTransition):
        apply_transition(ctx, request, C.START_WORK, RequestStatus.CLOSED)
