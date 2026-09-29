import pytest

from app.core import ids
from app.db import session as db_session
from app.db.models import Organization, Review
from app.modules.reputation import api as reputation
from app.modules.trust import api as trust
from tests import factories as base_factories
from tests.reputation import factories as rf
from tests.requests import helpers as h
from tests.support import idem, make_operator

pytestmark = pytest.mark.usefixtures("clean_db")


async def _publish_review(world, operator, *, rating: int, key: str) -> None:
    completed = await h.make_completion_reported(world)
    review = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=rating, text="Отзыв"),
            idem=idem(f"{key}-submit"),
        )
    ).body
    await reputation.decide_review(
        operator, ids.decode("review", review["id"]), "published", "ок", idem=idem(f"{key}-decide")
    )


async def test_ten_orders_from_one_company_is_one_vote() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-spike")
    world = await rf.add_customer_world(shared, name="Сеть №1")

    for i in range(10):
        await _publish_review(world, operator, rating=5 if i % 2 == 0 else 1, key=f"spike-{i}")

    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.unique_customers == 1
    assert summary.label == "Мало отзывов"
    assert summary.average is None
    assert summary.published_reviews_count == 10


async def test_three_organizations_give_a_number_two_give_label() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-three")

    two_orgs = [await rf.add_customer_world(shared, name=f"Заказчик-{i}") for i in range(2)]
    for i, world in enumerate(two_orgs):
        await _publish_review(world, operator, rating=4, key=f"two-{i}")

    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.unique_customers == 2
    assert summary.label == "Мало отзывов"
    assert summary.average is None

    third_world = await rf.add_customer_world(shared, name="Заказчик-третий")
    await _publish_review(third_world, operator, rating=4, key="three-3")

    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.unique_customers == 3
    assert summary.label is None
    assert summary.average == 4.0


async def test_rounding_is_half_up_not_banker() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-round")
    ratings = [4, 4, 4, 5]
    worlds = [
        await rf.add_customer_world(shared, name=f"Округление-{i}") for i in range(len(ratings))
    ]
    for i, (world, rating) in enumerate(zip(worlds, ratings, strict=True)):
        await _publish_review(world, operator, rating=rating, key=f"round-{i}")

    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.average == 4.3


async def test_provider_rename_does_not_reset_rating() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-rename")
    worlds = [await rf.add_customer_world(shared, name=f"Ренейм-{i}") for i in range(3)]
    for i, world in enumerate(worlds):
        await _publish_review(world, operator, rating=5, key=f"rename-{i}")

    async with db_session.transaction() as session:
        org = await session.get(Organization, shared.organization_id)
        assert org is not None
        org.display_name = "Новое имя сервиса"
        await session.flush()
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.average == 5.0
    assert summary.unique_customers == 3


async def test_unverified_customer_does_not_count() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-unverified")
    verified_worlds = [
        await rf.add_customer_world(shared, name=f"Проверенный-{i}") for i in range(2)
    ]
    unverified_world = await rf.add_customer_world(shared, name="Непроверенный", verified=False)

    for i, world in enumerate(verified_worlds):
        await _publish_review(world, operator, rating=5, key=f"verified-{i}")
    await _publish_review(unverified_world, operator, rating=1, key="unverified")

    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.unique_customers == 2
    assert summary.published_reviews_count == 3

    await _approve_customer(unverified_world, operator)
    async with db_session.transaction() as session:
        summary = await reputation.get_rating_summary(session, shared.organization_id)
    assert summary.unique_customers == 3
    assert summary.average is not None


async def _approve_customer(world, operator) -> None:  # type: ignore[no-untyped-def]
    async with db_session.transaction() as session:
        org = await session.get(Organization, world.customer_org_id)
        assert org is not None
        org.representative_verification_status = "pending"
        case = await base_factories.create_verification_case(
            session,
            org,
            check_kind="customer_representative",
            subject_type="customer_representative",
        )
        case_id = case.id
    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", case_id),
        trust.VerificationDecisionData(decision="approved", reason="договор", source="договор"),
        idem=idem(f"approve-{world.customer_org_id}"),
    )


async def _submit(world, *, rating: int, key: str) -> str:  # type: ignore[no-untyped-def]
    completed = await h.make_completion_reported(world)
    review = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=rating, text="Отзыв"),
            idem=idem(f"{key}-submit"),
        )
    ).body
    return str(review["id"])


async def _summary(provider_org_id):  # type: ignore[no-untyped-def]
    async with db_session.transaction() as session:
        return await reputation.get_rating_summary(session, provider_org_id)


async def test_rating_follows_edit_fraud_flag_removal_and_restore() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-follow")
    worlds = [await rf.add_customer_world(shared, name=f"След-{i}") for i in range(3)]
    review_ids = []
    for i, world in enumerate(worlds):
        review_id = await _submit(world, rating=5 if i else 2, key=f"follow-{i}")
        await reputation.decide_review(
            operator, ids.decode("review", review_id), "published", None, idem=idem(f"fp-{i}")
        )
        review_ids.append(review_id)
    assert (await _summary(shared.organization_id)).average == 4.0

    completed_request = await _request_of(review_ids[0])
    await reputation.submit_review(
        worlds[0].manager,
        completed_request,
        reputation.ReviewSubmitData(rating=1, text="Хуже"),
        idem=idem("follow-edit"),
    )
    summary = await _summary(shared.organization_id)
    assert summary.unique_customers == 2
    assert summary.published_reviews_count == 2

    await reputation.mark_suspected_fraud(
        operator, ids.decode("review", review_ids[1]), True, "накрутка", idem=idem("follow-f")
    )
    assert (await _summary(shared.organization_id)).unique_customers == 1

    await reputation.decide_review(
        operator, ids.decode("review", review_ids[2]), "removed", "спам", idem=idem("follow-rm")
    )
    assert (await _summary(shared.organization_id)).published_reviews_count == 1
    await reputation.decide_review(
        operator, ids.decode("review", review_ids[2]), "published", None, idem=idem("follow-rs")
    )
    assert (await _summary(shared.organization_id)).published_reviews_count == 2


async def _request_of(review_id: str):  # type: ignore[no-untyped-def]
    async with db_session.transaction() as session:
        review = await session.get(Review, ids.decode("review", review_id))
        assert review is not None
        return review.request_id
