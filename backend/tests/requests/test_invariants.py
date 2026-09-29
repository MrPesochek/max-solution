from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, InvalidTransition, ValidationFailed
from app.db import session as db_session
from app.db.enums import AssignmentState
from app.db.models import (
    Assignment,
    CancellationRequest,
    Equipment,
    IntegrationEvent,
    Offer,
    ProviderProfile,
    RepairQuote,
    RepairRequest,
    VisitProposal,
)
from app.infra.config import get_settings
from app.modules.requests import api, sweeper
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def _fresh_quarantine() -> Any:
    sweeper.reset_quarantine()
    yield
    sweeper.reset_quarantine()


async def _quote(world: World, body: dict[str, Any], clock: Clock, hours: int) -> dict[str, Any]:
    return (
        await api.create_repair_quote(
            world.dispatcher,
            h.rid(body),
            assignment_id=h.assignment_id(body),
            data=api.RepairQuoteInput(
                description_of_work="Замена компрессора",
                amount_minor=500000,
                currency="RUB",
                valid_until=clock.now + timedelta(hours=hours),
            ),
            expected_version=body["version"],
        )
    ).body


async def _propose(world: World, body: dict[str, Any], clock: Clock, hours: int) -> dict[str, Any]:
    return (
        await api.propose_visit(
            world.dispatcher,
            h.rid(body),
            assignment_id=h.assignment_id(body),
            data=api.VisitProposalInput(
                **h.visit_window(),
                amount_minor=120000,
                currency="RUB",
                valid_until=clock.now + timedelta(hours=hours),
            ),
            expected_version=body["version"],
        )
    ).body


async def _complete(world: World, body: dict[str, Any]) -> dict[str, Any]:
    return (
        await api.report_completion(
            world.dispatcher,
            h.rid(body),
            assignment_id=h.assignment_id(body),
            outcome="resolved",
            summary="Готово",
            expected_version=body["version"],
        )
    ).body


async def _set_provider_status(world: World, status: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.organization_id == world.provider_org_id)
            .values(status=status)
        )


async def _proposal_statuses(request_id: Any) -> dict[int, str]:
    async with db_session.transaction() as session:
        rows = await session.execute(
            select(VisitProposal.version, VisitProposal.status).where(
                VisitProposal.request_id == request_id
            )
        )
        return {version: status for version, status in rows.all()}


async def test_completion_supersedes_pending_children_and_sweeper_survives(
    world: World, clock: Clock
) -> None:
    """Репро аудита: смета и повторный выезд в in_progress → завершение → срок."""
    in_progress = await h.make_in_progress(world)
    quoted = await _quote(world, in_progress, clock, hours=1)
    proposed = await _propose(world, quoted, clock, hours=1)
    reported = await _complete(world, proposed)
    assert reported["status"] == "completion_reported"

    quote = await h.reload(RepairQuote, h.quote_id(quoted))
    assert quote.status == "superseded"
    assert (await _proposal_statuses(h.rid(reported)))[2] == "superseded"

    other = await h.make_accepted(world)
    other_proposed = await _propose(world, other, clock, hours=1)
    clock.advance(hours=2)
    counters = await api.expire_due()
    assert counters["visit_proposals"] == 1
    assert counters["repair_quotes"] == 0
    other_row = await h.reload(VisitProposal, h.proposal_id(other_proposed))
    assert other_row.status == "expired"

    view = await api.get_request(world.manager, h.rid(reported))
    assert view.status == "completion_reported"


async def test_confirm_completion_supersedes_pending_visit_proposal(
    world: World, clock: Clock
) -> None:
    in_progress = await h.make_in_progress(world)
    proposed = await _propose(world, in_progress, clock, hours=10)
    reported = await _complete(world, proposed)
    async with db_session.transaction() as session:
        await session.execute(
            update(VisitProposal)
            .where(VisitProposal.request_id == h.rid(reported), VisitProposal.version == 2)
            .values(status="pending")
        )
    await api.confirm_completion(
        world.manager, h.rid(reported), expected_version=reported["version"]
    )
    assert (await _proposal_statuses(h.rid(reported)))[2] == "superseded"


async def test_child_expiring_after_request_left_work_is_just_marked(
    world: World, clock: Clock
) -> None:
    in_progress = await h.make_in_progress(world)
    quoted = await _quote(world, in_progress, clock, hours=1)
    reported = await _complete(world, quoted)
    async with db_session.transaction() as session:
        await session.execute(
            update(RepairQuote).where(RepairQuote.id == h.quote_id(quoted)).values(status="pending")
        )
    clock.advance(hours=2)

    counters = await api.expire_due()
    assert counters["repair_quotes"] == 1
    assert (await h.reload(RepairQuote, h.quote_id(quoted))).status == "expired"
    view = await api.get_request(world.manager, h.rid(reported))
    assert view.status == "completion_reported"
    assert view.version == reported["version"]
    history, _ = await api.request_history(world.manager, h.rid(reported))
    assert "RepairQuoteExpired" not in [event.event_type for event in history]


async def test_failing_record_is_isolated_and_quarantined(
    world: World, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = await _propose(world, await h.make_accepted(world), clock, hours=1)
    healthy = await _propose(world, await h.make_accepted(world), clock, hours=1)
    clock.advance(hours=2)

    original = sweeper._notify_expiry
    attempts: list[Any] = []

    async def flaky(ctx: Any, request: RepairRequest, kind: str) -> None:
        if request.id == h.rid(broken):
            attempts.append(request.id)
            raise RuntimeError("сбой доставки")
        await original(ctx, request, kind)

    monkeypatch.setattr(sweeper, "_notify_expiry", flaky)
    counters = await api.expire_due()
    assert counters["visit_proposals"] == 1
    assert (await h.reload(VisitProposal, h.proposal_id(healthy))).status == "expired"
    assert (await h.reload(VisitProposal, h.proposal_id(broken))).status == "pending"
    assert len(attempts) == 1

    assert (await api.expire_due())["visit_proposals"] == 0
    assert len(attempts) == 1

    monkeypatch.setattr(sweeper, "_notify_expiry", original)
    clock.advance(minutes=5)
    assert (await api.expire_due())["visit_proposals"] == 1
    assert (await h.reload(VisitProposal, h.proposal_id(broken))).status == "expired"


async def test_rival_offers_expire_during_reservation(world: World, clock: Clock) -> None:
    published, rival = await h.make_published_with_rival(world)
    mine = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    rivals = (
        await api.submit_offer(
            rival.dispatcher,
            h.rid(published),
            data=api.OfferInput(amount_minor=90000, valid_until=clock.now + timedelta(minutes=20)),
        )
    ).body
    await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(mine))
    clock.advance(minutes=30)

    counters = await api.expire_due()
    assert counters["offers"] == 1
    assert (await h.reload(Offer, h.oid(rivals))).state == "expired"
    assert (await api.expire_due())["offers"] == 0


async def test_change_provider_before_acceptance_revokes_own_service(world: World) -> None:
    submitted = await h.make_submitted(world)
    changed = (
        await api.request_cancellation(
            world.manager,
            h.rid(submitted),
            target="change_provider",
            expected_version=submitted["version"],
        )
    ).body
    assert changed["status"] == "action_required"
    assert changed["assignment"]["state"] == "revoked"
    assert "assignment.revoked" in await h.event_types()


async def test_change_provider_during_reservation_returns_to_manager(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    changed = (
        await api.request_cancellation(
            world.manager,
            h.rid(published),
            target="change_provider",
            expected_version=selected["version"],
        )
    ).body
    assert changed["status"] == "action_required"
    assert (await h.reload(Assignment, h.assignment_id(selected))).state == "revoked"
    assert (await h.public_card(published)).status == "closed"

    cancelled = (
        await api.request_cancellation(world.manager, h.rid(published), target="cancel_request")
    ).body
    assert cancelled["status"] == "cancelled"


async def test_suspended_provider_cannot_accept(world: World) -> None:
    submitted = await h.make_submitted(world)
    await _set_provider_status(world, "suspended")
    with pytest.raises(Conflict) as exc:
        await api.accept_assignment(
            world.dispatcher, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"


async def test_suspended_provider_cannot_be_selected_or_confirm(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    await _set_provider_status(world, "suspended")
    with pytest.raises(Conflict) as exc:
        await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"

    await _set_provider_status(world, "active")
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    await _set_provider_status(world, "rejected")
    with pytest.raises(Conflict) as exc:
        await api.accept_assignment(
            world.dispatcher, h.rid(published), assignment_id=h.assignment_id(selected)
        )
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"


async def test_update_details_in_action_required(world: World) -> None:
    submitted = await h.make_submitted(world)
    declined = (
        await api.decline_assignment(
            world.dispatcher,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            reason="Нет мастера",
        )
    ).body
    snapshot = (await h.reload(RepairRequest, h.rid(submitted))).equipment_snapshot

    with pytest.raises(Forbidden):
        await api.update_request_details(world.employee, h.rid(submitted), urgency="critical")

    updated = (
        await api.update_request_details(
            world.manager,
            h.rid(submitted),
            urgency="critical",
            symptom_description="Не морозит совсем",
            expected_version=declined["version"],
        )
    ).body
    assert updated["urgency"] == "critical"
    assert updated["version"] == declined["version"] + 1
    row = await h.reload(RepairRequest, h.rid(submitted))
    assert row.symptom_description == "Не морозит совсем"
    assert row.equipment_snapshot == snapshot

    history, _ = await api.request_history(world.manager, h.rid(submitted))
    assert history[-1].event_type == "RequestDetailsUpdated"
    assert history[-1].payload["changed_fields"] == ["symptom_description", "urgency"]

    with pytest.raises(ValidationFailed):
        await api.update_request_details(world.manager, h.rid(submitted), urgency="critical")
    with pytest.raises(ValidationFailed):
        await api.update_request_details(
            world.manager, h.rid(submitted), published_description="Шкаф"
        )


async def test_update_details_changes_card_fields_after_no_providers() -> None:
    world = await h.build_world_without_providers()
    draft = await h.make_marketplace_draft(world)
    nobody = (
        await api.publish_search(world.manager, h.rid(draft), expected_version=draft["version"])
    ).body
    assert nobody["status"] == "action_required"
    updated = (
        await api.update_request_details(
            world.manager,
            h.rid(draft),
            published_description="Холодильный шкаф, не держит +4",
            district_id=None,
            expected_version=nobody["version"],
        )
    ).body
    card = await h.public_card(draft)
    assert card.published_description == "Холодильный шкаф, не держит +4"
    assert card.district_id is None
    assert card.status == "closed"
    assert updated["status"] == "action_required"


async def test_update_details_only_in_action_required(world: World) -> None:
    submitted = await h.make_submitted(world)
    with pytest.raises(InvalidTransition):
        await api.update_request_details(world.manager, h.rid(submitted), urgency="critical")


async def test_completion_reminders_24h_and_72h_once_each(world: World, clock: Clock) -> None:
    reported = await h.make_completion_reported(world)
    assert (await api.expire_due())["completion_reminders"] == 0

    clock.advance(hours=25)
    assert (await api.expire_due())["completion_reminders"] == 1
    assert (await api.expire_due())["completion_reminders"] == 0
    clock.advance(hours=48)
    assert (await api.expire_due())["completion_reminders"] == 1
    clock.advance(hours=48)
    assert (await api.expire_due())["completion_reminders"] == 0

    reminders = [n for n in await h.notifications() if n.notification_type == "completion.reminder"]
    assert [n.payload["reminder"] for n in reminders] == ["24h", "72h"]
    assert {n.recipient_membership_id for n in reminders} == {world.manager.membership_id}
    closed = (
        await api.confirm_completion(
            world.manager, h.rid(reported), expected_version=reported["version"]
        )
    ).body
    assert closed["status"] == "closed"
    assert closed["closure_kind"] == "customer_confirmed"


async def test_reminders_restart_after_rejected_completion(world: World, clock: Clock) -> None:
    reported = await h.make_completion_reported(world)
    clock.advance(hours=25)
    assert (await api.expire_due())["completion_reminders"] == 1
    clock.advance(minutes=1)
    rejected = (
        await api.reject_completion(
            world.manager,
            h.rid(reported),
            reason="Снова течёт",
            expected_version=reported["version"],
        )
    ).body
    await _complete(world, rejected)
    assert (await api.expire_due())["completion_reminders"] == 0
    clock.advance(hours=25)
    assert (await api.expire_due())["completion_reminders"] == 1


async def test_auto_close_when_enabled(
    world: World, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    reported = await h.make_completion_reported(world)
    clock.advance(days=3)
    assert "auto_closed" in await api.expire_due()
    view = await api.get_request(world.manager, h.rid(reported))
    assert view.status == "completion_reported"

    monkeypatch.setattr(get_settings(), "auto_close_days", 2)
    counters = await api.expire_due()
    assert counters["auto_closed"] == 1
    view = await api.get_request(world.manager, h.rid(reported))
    assert view.status == "closed"
    assert view.closure_kind == "auto_timeout"
    assignment = await h.reload(Assignment, h.assignment_id(reported))
    assert assignment.state == AssignmentState.COMPLETED
    types = await h.notification_types()
    assert "request.auto_closed" in types
    assert types.count("request.closed") >= 1
    assert (await api.expire_due())["auto_closed"] == 0


async def test_offers_do_not_invalidate_selection_form(world: World) -> None:
    published, rival = await h.make_published_with_rival(world)
    mine = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    await api.submit_offer(rival.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1))
    selected = (
        await api.select_offer(
            world.manager,
            h.rid(published),
            offer_id=h.oid(mine),
            expected_version=published["version"],
        )
    ).body
    assert selected["status"] == "awaiting_assignment_confirmation"


async def test_superseded_offer_version_cannot_be_selected(world: World) -> None:
    published = await h.make_published(world)
    first = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    await api.submit_offer(
        world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=90000)
    )
    with pytest.raises(Conflict) as exc:
        await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(first))
    assert exc.value.code == "OFFER_NOT_CURRENT"


async def test_republished_card_uses_request_snapshot(world: World) -> None:
    published = await h.make_published(world)
    async with db_session.transaction() as session:
        other_category = await factories.category_by_index(session, 1)
        await session.execute(
            update(Equipment)
            .where(Equipment.id == world.equipment_id)
            .values(equipment_category_id=other_category)
        )
    changed = (
        await api.request_cancellation(world.manager, h.rid(published), target="change_provider")
    ).body
    republished = (
        await api.publish_search(
            world.manager, h.rid(published), expected_version=changed["version"]
        )
    ).body
    assert republished["status"] == "searching"
    card = await h.public_card(published)
    assert card.equipment_category_id == world.category_id


async def test_provider_history_is_limited_to_its_assignment(world: World) -> None:
    published, rival = await h.make_published_with_rival(world)
    mine = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    theirs = (
        await api.submit_offer(
            rival.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=90000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(mine))).body
    await api.accept_assignment(
        world.integration, h.rid(published), assignment_id=h.assignment_id(selected)
    )
    await api.set_external_reference(world.integration, h.rid(published), external_id="CRM-7")

    history, _ = await api.request_history(world.dispatcher, h.rid(published))
    types = [event.event_type for event in history]
    assert "SearchPublished" not in types
    assert "RequestDrafted" not in types
    offer_ids = {event.payload.get("offer_id") for event in history}
    assert theirs["id"] not in offer_ids
    assert mine["id"] in offer_ids
    assert types[-1] == "ExternalReferenceLinked"
    assert history[-1].payload == {"external_id": "CRM-7"}

    customer_history, _ = await api.request_history(world.manager, h.rid(published))
    by_type = {event.event_type: event for event in customer_history}
    assert by_type["ExternalReferenceLinked"].payload == {}
    assert by_type["SearchPublished"].payload["matched_providers"] == 2


async def test_late_confirmation_releases_reservation_durably(world: World, clock: Clock) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    clock.advance(hours=3)
    with pytest.raises(Conflict) as exc:
        await api.accept_assignment(
            world.dispatcher, h.rid(published), assignment_id=h.assignment_id(selected)
        )
    assert exc.value.code == "ASSIGNMENT_EXPIRED"
    assert (await h.reload(Assignment, h.assignment_id(selected))).state == "expired"
    view = await api.get_request(world.manager, h.rid(published))
    assert view.status == "searching"
    assert (await api.expire_due())["reservations"] == 0


async def test_database_rejects_second_pending_proposal(world: World, clock: Clock) -> None:
    proposed = await _propose(world, await h.make_accepted(world), clock, hours=5)
    row = await h.reload(VisitProposal, h.proposal_id(proposed))
    with pytest.raises(IntegrityError):
        async with db_session.transaction() as session:
            session.add(
                VisitProposal(
                    request_id=row.request_id,
                    assignment_id=row.assignment_id,
                    version=row.version + 1,
                    valid_until=row.valid_until,
                    status="pending",
                )
            )


async def test_database_rejects_second_open_cancellation(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Не нужно"
        )
    ).body
    row = await h.reload(CancellationRequest, h.cancellation_id(pending))
    with pytest.raises(IntegrityError):
        async with db_session.transaction() as session:
            session.add(
                CancellationRequest(
                    request_id=row.request_id,
                    assignment_id=row.assignment_id,
                    target="cancel_request",
                    previous_status="accepted",
                    initiated_by_membership_id=row.initiated_by_membership_id,
                    status="disputed",
                )
            )


async def test_database_rejects_second_active_offer(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    row = await h.reload(Offer, h.oid(offer))
    with pytest.raises(IntegrityError):
        async with db_session.transaction() as session:
            session.add(
                Offer(
                    request_id=row.request_id,
                    provider_org_id=row.provider_org_id,
                    version=row.version + 1,
                    valid_until=row.valid_until,
                    state="active",
                )
            )


async def test_flush_unique_maps_invariant_to_conflict(world: World, clock: Clock) -> None:
    from app.core.actor import SystemActor
    from app.core.pipeline import CommandContext, CommandResult, run_command
    from app.modules.requests import support

    proposed = await _propose(world, await h.make_accepted(world), clock, hours=5)
    row = await h.reload(VisitProposal, h.proposal_id(proposed))

    async def handler(ctx: CommandContext) -> CommandResult:
        ctx.session.add(
            VisitProposal(
                request_id=row.request_id,
                assignment_id=row.assignment_id,
                version=row.version + 1,
                valid_until=row.valid_until,
                status="pending",
            )
        )
        await support.flush_unique(ctx)
        return CommandResult({})

    with pytest.raises(Conflict) as exc:
        await run_command(SystemActor(name="test"), handler)
    assert exc.value.code == "PROPOSAL_NOT_CURRENT"


async def test_request_assigned_is_sent_once_for_own_service(world: World) -> None:
    accepted = await h.make_accepted(world)
    async with db_session.transaction() as session:
        stmt = select(IntegrationEvent.event_type).where(
            IntegrationEvent.resource_id == h.rid(accepted)
        )
        types = list((await session.execute(stmt)).scalars())
    assert types.count("request.assigned") == 1
