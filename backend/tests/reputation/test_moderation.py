import pytest
from sqlalchemy import select

from app.core import ids
from app.core.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.db import session as db_session
from app.db.models import AuditEntry
from app.modules.reputation import api as reputation
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem, make_operator

pytestmark = pytest.mark.usefixtures("clean_db")


async def _submitted_review(world: World, *, rating: int = 4, key: str = "review") -> dict:
    completed = await h.make_completion_reported(world)
    return (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=rating, text="Хороший сервис"),
            idem=idem(key),
        )
    ).body


async def test_provider_cannot_publish_or_remove_review(world: World) -> None:
    review = await _submitted_review(world)
    review_id = ids.decode("review", review["id"])
    with pytest.raises(Forbidden):
        await reputation.decide_review(
            world.provider_admin, review_id, "published", "одобряю", idem=idem("provider-decide")
        )


async def test_operator_decision_requires_reason_for_rejection(world: World) -> None:
    review = await _submitted_review(world)
    operator = await make_operator("op-reason")
    review_id = ids.decode("review", review["id"])
    with pytest.raises(ValidationFailed):
        await reputation.decide_review(operator, review_id, "rejected", "", idem=idem("no-reason"))


async def test_operator_publishes_and_audit_is_recorded(world: World) -> None:
    review = await _submitted_review(world)
    operator = await make_operator("op-publish")
    review_id = ids.decode("review", review["id"])

    published = (
        await reputation.decide_review(
            operator, review_id, "published", "содержание уместно", idem=idem("publish")
        )
    ).body
    assert published["moderation_status"] == "published"

    async with db_session.transaction() as session:
        actions = {
            row.action
            for row in (
                await session.execute(select(AuditEntry).where(AuditEntry.object_id == review_id))
            ).scalars()
        }
    assert "review.moderate" in actions


async def test_operator_removes_published_review_with_reason(world: World) -> None:
    review = await _submitted_review(world)
    operator = await make_operator("op-remove")
    review_id = ids.decode("review", review["id"])
    await reputation.decide_review(operator, review_id, "published", "ок", idem=idem("publish-2"))

    with pytest.raises(ValidationFailed):
        await reputation.decide_review(operator, review_id, "removed", "", idem=idem("remove-bad"))

    removed = (
        await reputation.decide_review(
            operator, review_id, "removed", "подтверждена подделка", idem=idem("remove-ok")
        )
    ).body
    assert removed["moderation_status"] == "removed"


async def test_editing_does_not_create_second_vote_and_old_version_stays_public(
    world: World,
) -> None:
    review = await _submitted_review(world, rating=5, key="edit-flow")
    review_id = ids.decode("review", review["id"])
    operator = await make_operator("op-edit-flow")
    await reputation.decide_review(operator, review_id, "published", "ок", idem=idem("edit-pub"))

    published_list, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert len(published_list) == 1
    assert published_list[0].rating == 5

    edited = (
        await reputation.submit_review(
            world.manager,
            ids.decode("request", review["request_id"]),
            reputation.ReviewSubmitData(rating=2, text="Пересмотрел мнение"),
            idem=idem("edit-again"),
        )
    ).body
    assert edited["version"] == 2
    assert edited["moderation_status"] == "pending"

    still_public, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert len(still_public) == 1
    assert still_public[0].rating == 5, "до решения модератора публично видна прежняя версия"

    await reputation.decide_review(operator, review_id, "published", "ок", idem=idem("edit-pub-2"))
    now_public, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert now_public[0].rating == 2


async def test_single_reply_from_provider(world: World) -> None:
    review = await _submitted_review(world)
    review_id = ids.decode("review", review["id"])

    reply = (
        await reputation.reply_to_review(
            world.provider_admin, review_id, "Спасибо за отзыв", idem=idem("reply-1")
        )
    ).body
    assert reply["body"] == "Спасибо за отзыв"

    with pytest.raises(InvalidTransition):
        await reputation.reply_to_review(
            world.provider_admin, review_id, "Ещё раз спасибо", idem=idem("reply-2")
        )


async def test_appeal_creates_new_moderation_case(world: World) -> None:
    review = await _submitted_review(world)
    review_id = ids.decode("review", review["id"])
    operator = await make_operator("op-appeal")
    await reputation.decide_review(
        operator, review_id, "rejected", "нет права публикации", idem=idem("reject-for-appeal")
    )

    appeal = (
        await reputation.appeal_review(
            world.manager, review_id, "Отзыв реальный, прошу пересмотреть", idem=idem("appeal-1")
        )
    ).body
    assert appeal["subject_type"] == "review"
    assert appeal["appeal_status"] == "pending"

    cases, _ = await reputation.list_moderation_case_queue(operator, subject_type="review")
    assert any(c.id == appeal["id"] for c in cases)

    decided = (
        await reputation.decide_moderation_case(
            operator,
            ids.decode("moderation_case", appeal["id"]),
            "published",
            "обоснованно",
            idem=idem("appeal-decide"),
        )
    ).body
    assert decided["status"] == "published"
    assert decided["appeal_status"] == "resolved"


async def test_isolation_foreign_review_reply_404(world: World, other_world: World) -> None:
    review = await _submitted_review(world)
    review_id = ids.decode("review", review["id"])
    with pytest.raises(NotFound):
        await reputation.reply_to_review(
            other_world.provider_admin, review_id, "Чужой ответ", idem=idem("foreign-reply")
        )


async def test_isolation_foreign_complaint_not_listed(world: World, other_world: World) -> None:
    await reputation.create_complaint(
        world.manager,
        reputation.ComplaintCreateData(
            subject_type="provider_profile",
            target_id=ids.encode("organization", world.provider_org_id),
            description="Подозрительный профиль",
        ),
        idem=idem("complaint-1"),
    )
    mine, _ = await reputation.list_my_complaints(world.manager)
    theirs, _ = await reputation.list_my_complaints(other_world.manager)
    assert len(mine) == 1
    assert len(theirs) == 0


async def test_customer_side_of_provider_org_does_not_see_pending_review(world: World) -> None:
    """Организация в двух ролях: её сторона заказчика не видит неопубликованный
    отзыв о ней как об исполнителе."""
    from app.core.actor import UserActor
    from app.db.models import Organization
    from tests.requests import factories

    review = await _submitted_review(world, key="dual-review")
    async with db_session.transaction() as session:
        provider = await session.get(Organization, world.provider_org_id)
        assert provider is not None
        provider.is_customer = True
        user = await factories.create_user(session, "Закупщик исполнителя")
        membership = await factories.create_membership(session, user, provider, "customer_manager")
        customer_side = UserActor(
            user_id=user.id,
            membership_id=membership.id,
            organization_id=provider.id,
            role="customer_manager",
        )

    with pytest.raises(NotFound):
        await reputation.create_complaint(
            customer_side,
            reputation.ComplaintCreateData(
                subject_type="review", target_id=review["id"], description="Неправда"
            ),
            idem=idem("dual-complaint"),
        )
    await reputation.create_complaint(
        world.provider_admin,
        reputation.ComplaintCreateData(
            subject_type="review", target_id=review["id"], description="Неправда"
        ),
        idem=idem("provider-complaint"),
    )
    theirs, _ = await reputation.list_my_complaints(customer_side)
    assert theirs == []
