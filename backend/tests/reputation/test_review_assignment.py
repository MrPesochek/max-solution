import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.errors import Conflict, InvalidTransition, NotFound, RateLimited
from app.db import session as db_session
from app.db.models import (
    Equipment,
    Organization,
    ProviderProfile,
    RepairRequest,
    Review,
    ServiceBinding,
)
from app.infra.config import get_settings
from app.modules.reputation import api as reputation
from app.modules.reputation import queries as reputation_queries
from app.modules.requests import api as requests_api
from tests.requests import factories as req_factories
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem

pytestmark = pytest.mark.usefixtures("clean_db")


async def _switch_provider(world: World) -> World:
    """Привязка оборудования переходит к другому сервису."""
    rival = await req_factories.build_rival_provider(world)
    async with db_session.transaction() as session:
        binding = await session.get(ServiceBinding, world.binding_id)
        assert binding is not None
        binding.status = "revoked"
        equipment = await session.get(Equipment, world.equipment_id)
        customer = await session.get(Organization, world.customer_org_id)
        provider = await session.get(Organization, rival.provider_org_id)
        assert equipment is not None and customer is not None and provider is not None
        membership = await req_factories.create_membership(
            session,
            await req_factories.create_user(session, "Руководитель 2"),
            customer,
            "customer_manager",
        )
        await req_factories.create_binding(session, equipment, customer, provider, membership)
    return rival


async def _run_to_completion(world: World, request: dict[str, Any]) -> dict[str, Any]:
    accepted = (
        await requests_api.accept_assignment(
            world.dispatcher,
            h.rid(request),
            assignment_id=h.assignment_id(request),
            expected_version=request["version"],
        )
    ).body
    proposed = (
        await requests_api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=requests_api.VisitProposalInput(
                **h.visit_window(), amount_minor=100000, currency="RUB"
            ),
            expected_version=accepted["version"],
        )
    ).body
    scheduled = (
        await requests_api.approve_visit_proposal(
            world.manager,
            h.rid(proposed),
            proposal_id=h.proposal_id(proposed),
            proposal_version=proposed["visit_proposals"][0]["version"],
            expected_version=proposed["version"],
        )
    ).body
    started = (
        await requests_api.start_work(
            world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )
    ).body
    return (
        await requests_api.report_completion(
            world.dispatcher,
            h.rid(started),
            assignment_id=h.assignment_id(started),
            outcome="resolved",
            summary="Готово",
            expected_version=started["version"],
        )
    ).body


async def test_review_goes_to_assignment_that_worked_not_to_withdrawn_one(world: World) -> None:
    """Первый исполнитель отказался до начала работ — отзыв о ремонте получает
    второй, реально выполнивший работы; первое назначение явно выбрать нельзя."""
    accepted = await h.make_accepted(world)
    first_assignment = h.assignment_id(accepted)
    withdrawn = (
        await requests_api.withdraw_assignment(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=first_assignment,
            reason="Нет мастера",
        )
    ).body
    rival = await _switch_provider(world)
    resubmitted = (
        await requests_api.submit_to_own_service(
            world.manager, h.rid(withdrawn), expected_version=withdrawn["version"]
        )
    ).body
    assert h.assignment_id(resubmitted) != first_assignment
    completed = await _run_to_completion(rival, resubmitted)

    state = await reputation.get_review_state(world.manager, h.rid(completed))
    assert state.eligibility.assignment_id == ids.encode("assignment", h.assignment_id(resubmitted))
    with pytest.raises(NotFound):
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=1),
            idem=idem("withdrawn-explicit"),
            assignment_id=first_assignment,
        )

    review = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5),
            idem=idem("worked"),
        )
    ).body
    assert review["provider_organization_id"] == ids.encode("organization", rival.provider_org_id)
    assert review["assignment_id"] == ids.encode("assignment", h.assignment_id(resubmitted))


async def test_started_then_replaced_provider_gets_admission_review(world: World) -> None:
    """Работы начаты, затем исполнителя сменили: отзыв о плохом результате идёт
    к начавшему работы назначению через допуск модератора, а не к новому."""
    in_progress = await h.make_in_progress(world)
    first_assignment = h.assignment_id(in_progress)
    pending = (
        await requests_api.request_cancellation(
            world.manager, h.rid(in_progress), target="change_provider", reason="Не справились"
        )
    ).body
    released = (
        await requests_api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=first_assignment,
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
        )
    ).body
    await _switch_provider(world)
    resubmitted = (
        await requests_api.submit_to_own_service(
            world.manager, h.rid(released), expected_version=released["version"]
        )
    ).body
    assert h.assignment_id(resubmitted) != first_assignment

    state = await reputation.get_review_state(world.manager, h.rid(resubmitted))
    assert state.eligibility.mode == "needs_admission"
    assert state.eligibility.assignment_id == ids.encode("assignment", first_assignment)
    review = (
        await reputation.submit_review(
            world.manager,
            h.rid(resubmitted),
            reputation.ReviewSubmitData(rating=1, text="Бросили работы"),
            idem=idem("started"),
        )
    ).body
    assert review["provider_organization_id"] == ids.encode("organization", world.provider_org_id)


async def test_concurrent_first_review_creates_one_row(world: World) -> None:
    completed = await h.make_completion_reported(world)
    outcomes = await asyncio.gather(
        *(
            reputation.submit_review(
                world.manager,
                h.rid(completed),
                reputation.ReviewSubmitData(rating=4 + i),
                idem=idem(f"race-review-{i}"),
            )
            for i in range(2)
        ),
        return_exceptions=True,
    )
    assert all(not isinstance(o, BaseException) for o in outcomes), outcomes
    assert sorted(o.status for o in outcomes) == [200, 201]  # type: ignore[union-attr]
    async with db_session.transaction() as session:
        rows = list((await session.execute(select(Review))).scalars())
    assert len(rows) == 1
    assert rows[0].current_version == 2


async def test_duplicate_review_insert_is_conflict_not_500(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = await h.make_completion_reported(world)
    await reputation.submit_review(
        world.manager, h.rid(completed), reputation.ReviewSubmitData(rating=5), idem=idem("dup-1")
    )

    async def not_found(*_: object) -> None:
        return None

    monkeypatch.setattr(reputation_queries, "find_review", not_found)
    with pytest.raises(Conflict) as exc:
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=1),
            idem=idem("dup-2"),
        )
    assert exc.value.status == 409
    assert exc.value.code == "REVIEW_ALREADY_EXISTS"


async def test_employee_of_other_location_does_not_see_review(world: World) -> None:
    """L6: сотрудник видит отзыв только по заявкам своих точек."""
    completed = await h.make_completion_reported(world)
    await reputation.submit_review(
        world.manager, h.rid(completed), reputation.ReviewSubmitData(rating=5), idem=idem("loc")
    )
    own = await reputation.get_review_state(world.employee, h.rid(completed))
    assert own.review is not None
    with pytest.raises(NotFound):
        await reputation.get_review_state(world.other_employee, h.rid(completed))


def _complaint(subject: str, target: str) -> reputation.ComplaintCreateData:
    return reputation.ComplaintCreateData(
        subject_type=subject, target_id=target, description="Жалоба"
    )


async def test_complaint_requires_visible_target(world: World, other_world: World) -> None:
    """L9: жаловаться можно только на то, что заявитель видит."""
    completed = await h.make_completion_reported(world)
    review = (
        await reputation.submit_review(
            world.manager, h.rid(completed), reputation.ReviewSubmitData(rating=2), idem=idem("v")
        )
    ).body
    with pytest.raises(NotFound):
        await reputation.create_complaint(
            other_world.manager, _complaint("review", review["id"]), idem=idem("v-1")
        )
    created = await reputation.create_complaint(
        world.dispatcher, _complaint("review", review["id"]), idem=idem("v-2")
    )
    assert created.status == 201

    async with db_session.transaction() as session:
        profile = (
            await session.execute(
                select(ProviderProfile).where(
                    ProviderProfile.organization_id == other_world.provider_org_id
                )
            )
        ).scalar_one()
        profile.status = "draft"
    with pytest.raises(NotFound):
        await reputation.create_complaint(
            world.manager,
            _complaint("provider_profile", ids.encode("organization", other_world.provider_org_id)),
            idem=idem("v-3"),
        )
    with pytest.raises(NotFound):
        await reputation.create_complaint(
            other_world.manager,
            _complaint("no_show", ids.encode("request", h.rid(completed))),
            idem=idem("v-4"),
        )
    with pytest.raises(NotFound):
        await reputation.create_complaint(
            world.manager,
            _complaint("attachment", ids.encode("attachment", uuid.uuid4())),
            idem=idem("v-5"),
        )


async def test_complaints_are_rate_limited(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLAINT_LIMIT", "2")
    get_settings.cache_clear()
    target = ids.encode("organization", world.provider_org_id)
    for i in range(2):
        await reputation.create_complaint(
            world.manager, _complaint("provider_profile", target), idem=idem(f"rl-{i}")
        )
    with pytest.raises(RateLimited):
        await reputation.create_complaint(
            world.manager, _complaint("provider_profile", target), idem=idem("rl-3")
        )
    await reputation.create_complaint(
        world.employee, _complaint("provider_profile", target), idem=idem("rl-emp")
    )


async def test_no_show_complaint_points_to_assignment_with_agreed_visit(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    pending = (
        await requests_api.request_cancellation(
            world.manager, h.rid(scheduled), target="cancel_request", reason="Не приехали"
        )
    ).body
    await requests_api.respond_cancellation(
        world.dispatcher,
        h.rid(pending),
        assignment_id=h.assignment_id(pending),
        cancellation_id=h.cancellation_id(pending),
        decision="accept",
    )
    with pytest.raises(InvalidTransition):
        await reputation.submit_review(
            world.manager,
            h.rid(scheduled),
            reputation.ReviewSubmitData(rating=1),
            idem=idem("ns-review"),
        )
    complaint = await reputation.create_complaint(
        world.manager,
        _complaint("no_show", ids.encode("request", h.rid(scheduled))),
        idem=idem("ns"),
    )
    assert complaint.status == 201
    async with db_session.transaction() as session:
        request = await session.get(RepairRequest, h.rid(scheduled))
        assert request is not None
        target = await reputation_queries.no_show_assignment(session, request)
    assert target is not None and target.id == h.assignment_id(scheduled)


async def test_no_show_after_marketplace_offer_with_visit_terms(world: World) -> None:
    """T22: резерв с полным откликом подтверждается сразу с выездом — события
    VisitAgreed нет, но адресат жалобы на неявку всё равно известен."""
    published = await h.make_published(world)
    offer = (
        await requests_api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=requests_api.OfferInput(
                visit_window_start=h.window_start(),
                visit_window_end=h.window_end(),
                amount_minor=200000,
                currency="RUB",
                scope_description="Выезд, диагностика",
            ),
        )
    ).body
    selected = (
        await requests_api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))
    ).body
    confirmed = (
        await requests_api.accept_assignment(
            world.dispatcher,
            h.rid(published),
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    assert confirmed["status"] == "scheduled"

    async with db_session.transaction() as session:
        request = await session.get(RepairRequest, h.rid(published))
        assert request is not None
        target = await reputation_queries.no_show_assignment(session, request)
    assert target is not None and target.id == h.assignment_id(selected)
