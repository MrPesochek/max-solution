from datetime import timedelta

import pytest

from app.core.errors import Conflict
from app.db.models import RepairQuote, VisitProposal
from app.modules.requests import api
from app.modules.requests.sweeper import expire_due
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_expired_proposal_cannot_be_approved(world: World, clock: Clock) -> None:
    accepted = await h.make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(
                **h.visit_window(),
                amount_minor=100000,
                currency="RUB",
                valid_until=clock.now + timedelta(hours=2),
            ),
            expected_version=accepted["version"],
        )
    ).body
    clock.advance(hours=3)

    with pytest.raises(Conflict) as exc:
        await api.approve_visit_proposal(
            world.manager,
            h.rid(proposed),
            proposal_id=h.proposal_id(proposed),
            proposal_version=1,
        )
    assert exc.value.code == "PROPOSAL_EXPIRED"

    row = await h.reload(VisitProposal, h.proposal_id(proposed))
    assert row.status == "expired"
    counters = await expire_due()
    assert counters["visit_proposals"] == 0
    assert row.status == "expired"

    history, _ = await api.request_history(world.manager, h.rid(proposed))
    assert history[-1].event_type == "VisitProposalExpired"
    assert (await h.notification_types())[-1] == "visit_proposal.expired"

    assert (await expire_due())["visit_proposals"] == 0


async def test_expired_quote_is_swept(world: World, clock: Clock) -> None:
    in_progress = await h.make_in_progress(world)
    quoted = (
        await api.create_repair_quote(
            world.dispatcher,
            h.rid(in_progress),
            assignment_id=h.assignment_id(in_progress),
            data=api.RepairQuoteInput(
                description_of_work="Компрессор",
                amount_minor=500000,
                currency="RUB",
                valid_until=clock.now + timedelta(hours=1),
            ),
            expected_version=in_progress["version"],
        )
    ).body
    clock.advance(hours=2)
    counters = await expire_due()
    assert counters["repair_quotes"] == 1
    row = await h.reload(RepairQuote, h.quote_id(quoted))
    assert row.status == "expired"

    with pytest.raises(Conflict) as exc:
        await api.approve_repair_quote(
            world.manager, h.rid(quoted), quote_id=h.quote_id(quoted), quote_version=1
        )
    assert exc.value.code == "QUOTE_EXPIRED"


async def test_own_service_reminder_fires_once(world: World, clock: Clock) -> None:
    submitted = await h.make_submitted(world)
    assert (await expire_due())["reminders"] == 0

    clock.advance(hours=3)
    assert (await expire_due())["reminders"] == 1
    assert (await expire_due())["reminders"] == 0

    reminders = [
        n for n in await h.notifications() if n.notification_type == "own_service.no_answer"
    ]
    assert len(reminders) == 1
    assert reminders[0].recipient_membership_id == world.manager.membership_id

    history, _ = await api.request_history(world.manager, h.rid(submitted))
    assert [e.event_type for e in history].count("OwnServiceReminded") == 1
    view = await api.get_request(world.manager, h.rid(submitted))
    assert view.status == "awaiting_provider"


async def test_reminder_repeats_for_new_routing_attempt(world: World, clock: Clock) -> None:
    submitted = await h.make_submitted(world)
    clock.advance(hours=3)
    assert (await expire_due())["reminders"] == 1

    declined = (
        await api.decline_assignment(
            world.dispatcher,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            reason="Нет мастера",
        )
    ).body
    await api.submit_to_own_service(
        world.manager, h.rid(submitted), expected_version=declined["version"]
    )
    clock.advance(hours=3)
    assert (await expire_due())["reminders"] == 1

    reminders = [
        n for n in await h.notifications() if n.notification_type == "own_service.no_answer"
    ]
    assert len(reminders) == 2


async def test_reminder_is_not_sent_after_answer(world: World, clock: Clock) -> None:
    await h.make_accepted(world)
    clock.advance(hours=5)
    assert (await expire_due())["reminders"] == 0


async def test_proposal_ttl_is_capped(world: World, clock: Clock) -> None:
    accepted = await h.make_accepted(world)
    from app.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(
                **h.visit_window(),
                amount_minor=1000,
                currency="RUB",
                valid_until=clock.now + timedelta(hours=100),
            ),
            expected_version=accepted["version"],
        )
