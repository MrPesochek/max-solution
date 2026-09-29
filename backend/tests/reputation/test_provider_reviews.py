import pytest
from sqlalchemy import update

from app.core import ids
from app.core.errors import (
    Conflict,
    Forbidden,
    InvalidTransition,
    NotFound,
    RateLimited,
    ValidationFailed,
)
from app.db import session as db_session
from app.db.models import ProviderProfile
from app.infra.config import get_settings
from app.modules.reputation import api as reputation
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem, make_operator

pytestmark = pytest.mark.usefixtures("clean_db")


async def _published_review(world: World) -> dict[str, object]:
    completed = await h.make_completion_reported(world)
    review = (
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=2, text="Опоздали"),
            idem=idem("review"),
        )
    ).body
    operator = await make_operator("op-mine")
    await reputation.decide_review(
        operator, ids.decode("review", review["id"]), "published", "ок", idem=idem("publish")
    )
    return {**review, "request_number": completed["request_number"]}


async def test_provider_sees_own_reviews_with_request_number(world: World) -> None:
    review = await _published_review(world)
    items, _ = await reputation.list_my_reviews(world.provider_admin)
    assert [i.id for i in items] == [review["id"]]
    assert items[0].request_number == review["request_number"]
    assert items[0].rating == 2
    assert items[0].complaint is None

    public, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert "request_number" not in public[0].model_dump()


async def test_only_provider_side_reads_own_reviews(world: World, other_world: World) -> None:
    await _published_review(world)
    with pytest.raises(Forbidden):
        await reputation.list_my_reviews(world.manager)
    foreign, _ = await reputation.list_my_reviews(other_world.provider_admin)
    assert foreign == []


async def test_appeal_with_reason_code_and_withdraw(world: World) -> None:
    review = await _published_review(world)
    review_id = ids.decode("review", review["id"])
    with pytest.raises(ValidationFailed):
        await reputation.appeal_review(
            world.provider_admin, review_id, "Не наш", idem=idem("bad"), reason_code="spam"
        )
    appeal = (
        await reputation.appeal_review(
            world.provider_admin,
            review_id,
            "Мы не выезжали на этот адрес",
            idem=idem("appeal"),
            reason_code="not_our_work",
        )
    ).body
    assert appeal["reason_code"] == "not_our_work"
    assert appeal["review_id"] == review["id"]
    assert appeal["subject_id"] == review["id"]

    items, _ = await reputation.list_my_reviews(world.provider_admin)
    assert items[0].complaint is not None
    assert items[0].complaint.status == "pending"
    public, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert [p.id for p in public] == [review["id"]]

    case_id = ids.decode("moderation_case", appeal["id"])
    with pytest.raises(NotFound):
        await reputation.withdraw_complaint(world.manager, case_id, idem=idem("w-foreign"))
    with pytest.raises(Forbidden):
        await reputation.withdraw_complaint(world.dispatcher, case_id, idem=idem("w-dispatcher"))
    withdrawn = (
        await reputation.withdraw_complaint(world.provider_admin, case_id, idem=idem("w-own"))
    ).body
    assert withdrawn["status"] == "withdrawn"
    with pytest.raises(InvalidTransition):
        await reputation.withdraw_complaint(world.provider_admin, case_id, idem=idem("w-again"))

    operator = await make_operator("op-withdrawn")
    with pytest.raises(InvalidTransition):
        await reputation.decide_moderation_case(
            operator, case_id, "rejected", "поздно", idem=idem("decide-late")
        )
    complaints, _ = await reputation.list_my_complaints(world.provider_admin)
    assert complaints[0].status == "withdrawn"


async def test_foreign_organization_cannot_withdraw(world: World, other_world: World) -> None:
    review = await _published_review(world)
    appeal = (
        await reputation.appeal_review(
            world.provider_admin,
            ids.decode("review", review["id"]),
            "Оскорбления",
            idem=idem("appeal-2"),
            reason_code="abuse_or_personal_data",
        )
    ).body
    with pytest.raises(NotFound):
        await reputation.withdraw_complaint(
            other_world.provider_admin,
            ids.decode("moderation_case", appeal["id"]),
            idem=idem("w-other"),
        )


async def test_second_open_appeal_is_rejected_and_reappeal_after_withdraw_works(
    world: World,
) -> None:
    review = await _published_review(world)
    review_id = ids.decode("review", review["id"])
    first = (
        await reputation.appeal_review(
            world.provider_admin, review_id, "Не наш заказ", idem=idem("a-1")
        )
    ).body
    with pytest.raises(Conflict) as exc:
        await reputation.appeal_review(world.dispatcher, review_id, "Ещё раз", idem=idem("a-2"))
    assert exc.value.code == "APPEAL_ALREADY_OPEN"

    await reputation.withdraw_complaint(
        world.provider_admin, ids.decode("moderation_case", first["id"]), idem=idem("a-w")
    )
    again = (
        await reputation.appeal_review(
            world.provider_admin, review_id, "Подаём заново", idem=idem("a-3")
        )
    ).body
    assert again["status"] == "pending"


async def test_appeal_cycle_is_rate_limited(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLAINT_LIMIT", "2")
    get_settings.cache_clear()
    try:
        review = await _published_review(world)
        review_id = ids.decode("review", review["id"])
        for step in range(2):
            case = (
                await reputation.appeal_review(
                    world.provider_admin, review_id, "Не наш", idem=idem(f"c-{step}")
                )
            ).body
            await reputation.withdraw_complaint(
                world.provider_admin,
                ids.decode("moderation_case", case["id"]),
                idem=idem(f"cw-{step}"),
            )
        with pytest.raises(RateLimited):
            await reputation.appeal_review(
                world.provider_admin, review_id, "Снова", idem=idem("c-limit")
            )
    finally:
        get_settings.cache_clear()


async def test_suspended_provider_cannot_reply_or_appeal(world: World) -> None:
    review = await _published_review(world)
    review_id = ids.decode("review", review["id"])
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.organization_id == world.provider_org_id)
            .values(status="suspended")
        )
    with pytest.raises(Conflict) as exc:
        await reputation.reply_to_review(
            world.provider_admin, review_id, "Спасибо", idem=idem("s-reply")
        )
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"
    with pytest.raises(Conflict) as exc:
        await reputation.appeal_review(
            world.provider_admin, review_id, "Не наш", idem=idem("s-appeal")
        )
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"
    appeal = await reputation.appeal_provider_profile(
        world.provider_admin, "Документы в порядке", idem=idem("s-profile")
    )
    assert appeal.status == 201
    published, _ = await reputation.list_published_reviews(world.provider_org_id)
    assert published
