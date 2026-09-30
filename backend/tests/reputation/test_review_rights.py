import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import UserActor
from app.core.errors import Forbidden, InvalidTransition, NotFound
from app.db import session as db_session
from app.db.models import ModerationCase, Organization, Review
from app.modules.reputation import api as reputation
from app.modules.requests import api as requests_api
from tests.requests import factories as req_factories
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_a34_one_review_per_organization_second_manager_edits(world: World) -> None:
    completed = await h.make_completion_reported(world)

    created = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5, text="Отлично"),
            idem=idem("review-1"),
        )
    ).body
    assert created["rating"] == 5
    assert created["moderation_status"] == "pending"

    async with db_session.transaction() as session:
        second_user = await req_factories.create_user(session, "Второй руководитель")
        customer_org = await session.get(Organization, world.customer_org_id)
        assert customer_org is not None
        second_membership = await req_factories.create_membership(
            session, second_user, customer_org, role="customer_manager"
        )
    second_manager = UserActor(
        user_id=second_membership.user_id,
        membership_id=second_membership.id,
        organization_id=world.customer_org_id,
        role="customer_manager",
    )

    edited = (
        await reputation.submit_review(
            second_manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=2, text="Пересмотрели оценку"),
            idem=idem("review-2"),
        )
    ).body
    assert edited["id"] == created["id"]
    assert edited["rating"] == 2
    assert edited["version"] == 2

    async with db_session.transaction() as session:
        rows = (
            await session.execute(select(Review).where(Review.request_id == h.rid(completed)))
        ).scalars()
        assert len(list(rows)) == 1


async def test_cannot_review_arbitrary_provider(world: World) -> None:
    completed = await h.make_completion_reported(world)
    result = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=4),
            idem=idem("no-arbitrary"),
        )
    ).body
    assert result["provider_organization_id"] == ids.encode("organization", world.provider_org_id)


async def test_negative_review_allowed_without_completion_confirmation(world: World) -> None:
    completed = await h.make_completion_reported(world)
    result = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=1, text="Не устранили неисправность"),
            idem=idem("negative"),
        )
    ).body
    assert result["rating"] == 1


async def test_review_allowed_after_closed(world: World) -> None:
    completed = await h.make_completion_reported(world)
    closed = (
        await requests_api.confirm_completion(
            world.manager, h.rid(completed), expected_version=completed["version"]
        )
    ).body
    assert closed["status"] == "closed"
    result = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5),
            idem=idem("closed-review"),
        )
    ).body
    assert result["rating"] == 5


async def test_employee_cannot_submit_review(world: World) -> None:
    completed = await h.make_completion_reported(world)
    with pytest.raises(Forbidden):
        await reputation.submit_review(
            world.employee,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5),
            idem=idem("employee"),
        )


async def test_self_review_forbidden_for_shared_inn(world: World) -> None:
    completed = await h.make_completion_reported(world)
    async with db_session.transaction() as session:
        customer = await session.get(Organization, world.customer_org_id)
        provider = await session.get(Organization, world.provider_org_id)
        assert customer is not None and provider is not None
        customer.inn_normalized = "7700000000"
        provider.inn_normalized = "7700000000"
        await session.flush()

    with pytest.raises(Forbidden) as exc:
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5),
            idem=idem("self-review"),
        )
    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"


async def test_cancel_before_work_started_blocks_review(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await requests_api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Передумали"
        )
    ).body
    cancelled = (
        await requests_api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
        )
    ).body
    assert cancelled["status"] == "cancelled"

    with pytest.raises(InvalidTransition) as exc:
        await reputation.submit_review(
            world.manager,
            h.rid(cancelled),
            reputation.ReviewSubmitData(rating=1),
            idem=idem("blocked"),
        )
    assert exc.value.code == "REVIEW_NOT_ALLOWED"


async def test_no_show_complaint_only_after_scheduled(world: World) -> None:
    accepted = await h.make_accepted(world)
    pending = (
        await requests_api.request_cancellation(
            world.manager, h.rid(accepted), target="cancel_request", reason="Не нужно"
        )
    ).body
    cancelled = (
        await requests_api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
        )
    ).body

    with pytest.raises(InvalidTransition) as exc:
        await reputation.create_complaint(
            world.manager,
            reputation.ComplaintCreateData(
                subject_type="no_show",
                target_id=ids.encode("request", h.rid(cancelled)),
                description="Мастер не приехал",
            ),
            idem=idem("no-show-early"),
        )
    assert exc.value.code == "NO_SHOW_COMPLAINT_NOT_ALLOWED"

    scheduled = await h.make_scheduled(world)
    pending2 = (
        await requests_api.request_cancellation(
            world.manager, h.rid(scheduled), target="cancel_request", reason="Не приехали"
        )
    ).body
    cancelled2 = (
        await requests_api.respond_cancellation(
            world.dispatcher,
            h.rid(pending2),
            assignment_id=h.assignment_id(pending2),
            cancellation_id=h.cancellation_id(pending2),
            decision="accept",
        )
    ).body
    complaint = (
        await reputation.create_complaint(
            world.manager,
            reputation.ComplaintCreateData(
                subject_type="no_show",
                target_id=ids.encode("request", h.rid(cancelled2)),
                description="Мастер не приехал на согласованный выезд",
            ),
            idem=idem("no-show-ok"),
        )
    ).body
    assert complaint["subject_type"] == "no_show"
    assert complaint["status"] == "pending"


async def test_needs_admission_when_work_started_but_not_reported(world: World) -> None:
    in_progress = await h.make_in_progress(world)
    pending = (
        await requests_api.request_cancellation(
            world.manager, h.rid(in_progress), target="cancel_request", reason="Работы затянулись"
        )
    ).body
    cancelled = (
        await requests_api.respond_cancellation(
            world.dispatcher,
            h.rid(pending),
            assignment_id=h.assignment_id(pending),
            cancellation_id=h.cancellation_id(pending),
            decision="accept",
        )
    ).body

    result = (
        await reputation.submit_review(
            world.manager,
            h.rid(cancelled),
            reputation.ReviewSubmitData(rating=2, text="Работы не довели до конца"),
            idem=idem("needs-admission"),
        )
    ).body
    assert result["moderation_status"] == "pending"

    async with db_session.transaction() as session:
        cases = (
            await session.execute(
                select(ModerationCase).where(
                    ModerationCase.review_id == ids.decode("review", result["id"])
                )
            )
        ).scalars()
        kinds = {case.evidence.get("kind") for case in cases}
        assert "admission_required" in kinds


async def test_isolation_review_of_other_request_404(world: World, other_world: World) -> None:
    completed = await h.make_completion_reported(world)
    with pytest.raises(NotFound):
        await reputation.submit_review(
            other_world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5),
            idem=idem("foreign"),
        )
