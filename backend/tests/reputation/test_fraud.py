import pytest
from sqlalchemy import select

from app.core import ids
from app.db import session as db_session
from app.db.models import ModerationCase, Organization
from app.modules.reputation import api as reputation
from tests.reputation import factories as rf
from tests.requests import factories as req_factories
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem, make_operator

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_shared_members_flag_does_not_block_review_creation(world: World) -> None:
    """Общий пользователь в обеих организациях: отзыв принимается, но помечается."""
    completed = await h.make_completion_reported(world)
    async with db_session.transaction() as session:
        shared_user = await req_factories.create_user(session, "Общий сотрудник")
        customer_org = await session.get(Organization, world.customer_org_id)
        provider_org = await session.get(Organization, world.provider_org_id)
        assert customer_org is not None and provider_org is not None
        await req_factories.create_membership(
            session, shared_user, customer_org, role="customer_employee"
        )
        await req_factories.create_membership(
            session, shared_user, provider_org, role="provider_dispatcher"
        )

    result = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5, text="Отлично сработали"),
            idem=idem("shared-members"),
        )
    ).body
    assert result["moderation_status"] == "pending"

    async with db_session.transaction() as session:
        case = (
            await session.execute(
                select(ModerationCase).where(
                    ModerationCase.review_id == ids.decode("review", result["id"])
                )
            )
        ).scalar_one()
    assert case.evidence["signals"]["shared_members"]["triggered"] is True


async def test_suspected_fraud_does_not_hide_published_review_but_excludes_from_rating() -> None:
    shared = await rf.build_shared_provider()
    operator = await make_operator("op-fraud")
    worlds = [await rf.add_customer_world(shared, name=f"Накрутка-{i}") for i in range(3)]

    review_ids = []
    for i, world in enumerate(worlds):
        completed = await h.make_completion_reported(world)
        review = (
            await reputation.submit_review(
                world.manager,
                h.rid(completed),
                reputation.ReviewSubmitData(rating=5, text="Отзыв"),
                idem=idem(f"fraud-submit-{i}"),
            )
        ).body
        await reputation.decide_review(
            operator,
            ids.decode("review", review["id"]),
            "published",
            "ок",
            idem=idem(f"fraud-decide-{i}"),
        )
        review_ids.append(ids.decode("review", review["id"]))

    async with db_session.transaction() as session:
        before = await reputation.get_rating_summary(session, shared.organization_id)
    assert before.average == 5.0
    assert before.unique_customers == 3

    flagged = (
        await reputation.mark_suspected_fraud(
            operator, review_ids[0], True, "подозрение на накрутку", idem=idem("flag-fraud")
        )
    ).body
    assert flagged["suspected_fraud"] is True

    published_still, _ = await reputation.list_published_reviews(shared.organization_id)
    assert len(published_still) == 3, "флаг расследования не скрывает опубликованный отзыв"

    async with db_session.transaction() as session:
        after = await reputation.get_rating_summary(session, shared.organization_id)
    assert after.unique_customers == 2
    assert after.label == "Мало отзывов"
