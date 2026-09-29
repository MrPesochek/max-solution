from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.errors import Conflict, ValidationFailed
from app.db import session as db_session
from app.db.models import Assignment, ProviderProfile, RequestEvent, VisitProposal
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.conftest import Clock
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _propose(world: World, body: dict[str, Any], **data: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {"amount_minor": 150000, "currency": "RUB"}
    fields.update(data)
    result = await api.propose_visit(
        world.dispatcher,
        h.rid(body),
        assignment_id=h.assignment_id(body),
        data=api.VisitProposalInput(**fields),
        expected_version=body["version"],
    )
    return result.body


async def _approve(world: World, body: dict[str, Any]) -> dict[str, Any]:
    proposal = body["visit_proposals"][0]
    result = await api.approve_visit_proposal(
        world.manager,
        h.rid(body),
        proposal_id=h.proposal_id(body),
        proposal_version=proposal["version"],
        expected_version=body["version"],
    )
    return result.body


async def _mark_en_route(world: World, body: dict[str, Any]) -> dict[str, Any]:
    result = await api.mark_en_route(
        world.dispatcher,
        h.rid(body),
        assignment_id=h.assignment_id(body),
        expected_version=body["version"],
    )
    return result.body


async def _set_provider_status(world: World, status: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.organization_id == world.provider_org_id)
            .values(status=status)
        )


async def _last_event_payload(body: dict[str, Any], event_type: str) -> dict[str, Any]:
    async with db_session.transaction() as session:
        stmt = (
            select(RequestEvent.payload)
            .where(RequestEvent.request_id == h.rid(body), RequestEvent.event_type == event_type)
            .order_by(RequestEvent.occurred_at.desc(), RequestEvent.id.desc())
            .limit(1)
        )
        return dict((await session.execute(stmt)).scalar_one())


async def test_proposal_with_window_is_accepted(world: World) -> None:
    accepted = await h.make_accepted(world)
    proposed = await _propose(world, accepted, **h.visit_window())
    assert proposed["visit_proposals"][0]["status"] == "pending"
    scheduled = await _approve(world, proposed)
    assert scheduled["status"] == "scheduled"


@pytest.mark.parametrize(
    "window",
    [
        {},
        {"visit_window_start": "start"},
        {"visit_window_end": "end"},
    ],
)
async def test_proposal_needs_both_window_ends(world: World, window: dict[str, str]) -> None:
    accepted = await h.make_accepted(world)
    values = {"start": h.window_start(), "end": h.window_end()}
    data = {key: values[value] for key, value in window.items()}
    with pytest.raises(ValidationFailed) as exc:
        await _propose(world, accepted, **data)
    assert exc.value.code == "VISIT_WINDOW_REQUIRED"


async def test_proposal_rejects_inverted_and_past_window(world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(ValidationFailed) as exc:
        await _propose(
            world, accepted, visit_window_start=h.window_end(), visit_window_end=h.window_start()
        )
    assert exc.value.details["field"] == "visit_window_end"

    past = datetime.now(UTC) - timedelta(hours=3)
    with pytest.raises(ValidationFailed) as exc:
        await _propose(
            world,
            accepted,
            visit_window_start=past,
            visit_window_end=past + timedelta(hours=1),
        )
    assert exc.value.code == "VISIT_WINDOW_PASSED"


async def test_naive_datetimes_are_422_not_500(world: World) -> None:
    accepted = await h.make_accepted(world)
    naive_start = h.window_start().replace(tzinfo=None)
    with pytest.raises(ValidationFailed) as exc:
        await _propose(
            world, accepted, visit_window_start=naive_start, visit_window_end=h.window_end()
        )
    assert exc.value.details["field"] == "visit_window_start"

    naive_until = (datetime.now(UTC) + timedelta(hours=5)).replace(tzinfo=None)
    with pytest.raises(ValidationFailed) as exc:
        await _propose(world, accepted, **h.visit_window(), valid_until=naive_until)
    assert exc.value.details["field"] == "valid_until"


async def test_long_terms_text_is_rejected(world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(ValidationFailed) as exc:
        await _propose(world, accepted, **h.visit_window(), scope_description="x" * 2001)
    assert exc.value.details["field"] == "scope_description"
    proposed = await _propose(world, accepted, **h.visit_window(), comment="x" * 2000)
    assert proposed["visit_proposals"][0]["status"] == "pending"


async def test_passed_window_cannot_be_approved(world: World, clock: Clock) -> None:
    accepted = await h.make_accepted(world)
    proposed = await _propose(
        world,
        accepted,
        visit_window_start=clock.now + timedelta(hours=1),
        visit_window_end=clock.now + timedelta(hours=2),
        valid_until=clock.now + timedelta(hours=48),
    )
    clock.advance(hours=3)
    with pytest.raises(Conflict) as exc:
        await _approve(world, proposed)
    assert exc.value.code == "VISIT_WINDOW_PASSED"
    assert (await api.get_request(world.manager, h.rid(accepted))).status == "accepted"


async def test_stored_proposal_without_window_cannot_be_approved(world: World) -> None:
    accepted = await h.make_accepted(world)
    proposed = await _propose(world, accepted, **h.visit_window())
    async with db_session.transaction() as session:
        await session.execute(
            update(VisitProposal)
            .where(VisitProposal.id == h.proposal_id(proposed))
            .values(visit_window_start=None, visit_window_end=None)
        )
    with pytest.raises(Conflict) as exc:
        await _approve(world, proposed)
    assert exc.value.code == "VISIT_WINDOW_REQUIRED"


async def test_offer_window_is_optional_but_checked(world: World) -> None:
    published = await h.make_published(world)
    with pytest.raises(ValidationFailed) as exc:
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(visit_window_start=h.window_start(), amount_minor=1000),
        )
    assert exc.value.code == "VISIT_WINDOW_REQUIRED"
    past = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(ValidationFailed) as exc:
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                visit_window_start=past,
                visit_window_end=past + timedelta(hours=1),
                amount_minor=1000,
            ),
        )
    assert exc.value.code == "VISIT_WINDOW_PASSED"
    offer = await api.submit_offer(
        world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1000)
    )
    assert offer.status == 201


async def test_offer_window_passed_during_reservation_is_not_scheduled(
    world: World, clock: Clock
) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                visit_window_start=clock.now + timedelta(minutes=10),
                visit_window_end=clock.now + timedelta(minutes=40),
                amount_minor=200000,
                currency="RUB",
                scope_description="Выезд, диагностика",
            ),
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    clock.advance(hours=1)
    confirmed = (
        await api.accept_assignment(
            world.dispatcher,
            h.rid(published),
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    assert confirmed["status"] == "accepted"
    assert confirmed["visit_proposals"] == []


async def test_reschedule_resets_en_route_and_allows_new_mark(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    marked = await _mark_en_route(world, scheduled)
    assert marked["assignment"]["en_route_at"] is not None

    rescheduled = await _propose(
        world,
        marked,
        visit_window_start=h.window_start() + timedelta(days=1),
        visit_window_end=h.window_end() + timedelta(days=1),
    )
    assert rescheduled["status"] == "accepted"
    assert rescheduled["assignment"]["en_route_at"] is None
    payload = await _last_event_payload(marked, "VisitProposalSuperseded")
    assert payload["en_route_reset"] is True
    card = await api.get_request(world.manager, h.rid(marked))
    assert card.assignment is not None and card.assignment.en_route_at is None

    again = await _approve(world, rescheduled)
    assert again["status"] == "scheduled"
    remarked = await _mark_en_route(world, again)
    assert remarked["assignment"]["en_route_at"] is not None


async def test_reschedule_without_mark_keeps_event_clean(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    rescheduled = await _propose(world, scheduled, **h.visit_window())
    assert rescheduled["status"] == "accepted"
    payload = await _last_event_payload(scheduled, "VisitProposalSuperseded")
    assert "en_route_reset" not in payload


async def test_new_field_worker_resets_en_route(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    first = (
        await api.set_field_worker(
            world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            display_name="Иван",
            contact_phone=None,
            expected_version=scheduled["version"],
        )
    ).body
    marked = await _mark_en_route(world, first)

    same = (
        await api.set_field_worker(
            world.dispatcher,
            h.rid(marked),
            assignment_id=h.assignment_id(marked),
            display_name="Иван",
            contact_phone="+79990000000",
            expected_version=marked["version"],
        )
    ).body
    assert same["assignment"]["en_route_at"] is not None

    other = (
        await api.set_field_worker(
            world.dispatcher,
            h.rid(same),
            assignment_id=h.assignment_id(same),
            display_name="Пётр",
            contact_phone=None,
            expected_version=same["version"],
        )
    ).body
    assert other["assignment"]["en_route_at"] is None
    assert (await _last_event_payload(other, "FieldWorkerAssigned"))["en_route_reset"] is True
    remarked = await _mark_en_route(world, other)
    assert remarked["assignment"]["en_route_at"] is not None


async def test_needs_information_keeps_accepted_work_going(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    submitted = await h.make_submitted(world)
    await _set_provider_status(world, "needs_information")
    marked = await api.mark_en_route(
        world.integration,
        h.rid(scheduled),
        assignment_id=h.assignment_id(scheduled),
        expected_version=scheduled["version"],
    )
    started = await api.start_work(
        world.dispatcher,
        h.rid(scheduled),
        assignment_id=h.assignment_id(scheduled),
        expected_version=marked.body["version"],
    )
    assert started.body["status"] == "in_progress"

    with pytest.raises(Conflict) as exc:
        await api.accept_assignment(
            world.dispatcher, h.rid(submitted), assignment_id=h.assignment_id(submitted)
        )
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"


@pytest.mark.parametrize("status", ["suspended", "rejected"])
async def test_lost_status_blocks_changes_in_every_channel(world: World, status: str) -> None:
    scheduled = await h.make_scheduled(world)
    await _set_provider_status(world, status)
    for actor in (world.dispatcher, world.integration):
        with pytest.raises(Conflict) as exc:
            await api.mark_en_route(
                actor,
                h.rid(scheduled),
                assignment_id=h.assignment_id(scheduled),
                expected_version=scheduled["version"],
            )
        assert exc.value.code == "PROVIDER_NOT_ACTIVE"
    view = await api.get_request(world.integration, h.rid(scheduled))
    assert view.status == "scheduled"
    async with db_session.transaction() as session:
        row = await session.get(Assignment, h.assignment_id(scheduled))
        assert row is not None and row.en_route_at is None


async def test_preview_uses_details_of_existing_card() -> None:
    world = await h.build_world_without_providers()
    draft = await h.make_marketplace_draft(world)
    nobody = (
        await api.publish_search(world.manager, h.rid(draft), expected_version=draft["version"])
    ).body
    await api.update_request_details(
        world.manager,
        h.rid(draft),
        published_description="Холодильный шкаф, не держит +4",
        expected_version=nobody["version"],
    )
    preview = await api.preview_public_card(world.manager, h.rid(draft))
    assert preview.public_card.published_description == "Холодильный шкаф, не держит +4"
    explicit = await api.preview_public_card(
        world.manager, h.rid(draft), data=api.PublicCardInput(published_description="Новое")
    )
    assert explicit.public_card.published_description == "Новое"
    card = await h.public_card(draft)
    assert card.published_description == "Холодильный шкаф, не держит +4"
    assert card.status == "closed"
