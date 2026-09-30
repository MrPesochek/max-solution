from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core import ids
from app.core.actor import UserActor
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.models import RepairRequest
from app.demo import scenarios, seed
from app.modules.files import api as files
from app.modules.requests import api as requests
from app.modules.requests.views import RequestListItemView

pytestmark = pytest.mark.usefixtures("clean_db")

MANAGER = UserActor(
    user_id=seed._id("user:manager"),
    membership_id=seed._id("membership:customer:manager"),
    organization_id=seed.ORG_CUSTOMER,
    role="customer_manager",
)
EMPLOYEE = UserActor(
    user_id=seed._id("user:employee"),
    membership_id=seed._id("membership:customer:employee"),
    organization_id=seed.ORG_CUSTOMER,
    role="customer_employee",
    location_ids=frozenset({seed._id("location:customer:1")}),
)
PROVIDER_ADMIN = UserActor(
    user_id=seed._id("user:provider_admin"),
    membership_id=seed._id("membership:provider:admin"),
    organization_id=seed.ORG_PROVIDER,
    role="provider_admin",
)
PROVIDER_DISPATCHER = UserActor(
    user_id=seed._id("user:provider_dispatcher"),
    membership_id=seed._id("membership:provider:dispatcher"),
    organization_id=seed.ORG_PROVIDER,
    role="provider_dispatcher",
)


def _equipment(key: str) -> str:
    return ids.encode("equipment", seed._id(f"equipment:customer:{key}"))


async def _list(
    actor: UserActor, assignment_states: list[str] | None = None
) -> list[RequestListItemView]:
    items, _ = await requests.list_requests(actor, assignment_states=assignment_states, limit=100)
    return items


def _by_equipment(items: list[RequestListItemView], key: str) -> list[RequestListItemView]:
    return [item for item in items if item.equipment_id == _equipment(key)]


async def _demo_request_count() -> int:
    async with db_session.get_sessionmaker()() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(RepairRequest)
                    .where(RepairRequest.customer_org_id.in_(seed.DEMO_ORG_IDS))
                )
            ).scalar_one()
        )


async def test_manager_home_shows_decisions_with_amounts_and_deadlines() -> None:
    await seed.run()
    now = utcnow()
    items = await _list(MANAGER)

    statuses = sorted(item.status for item in items)
    assert statuses == sorted(
        [
            "accepted",
            "accepted",
            "searching",
            "searching",
            "in_progress",
            "in_progress",
            "awaiting_provider",
            "awaiting_provider",
            "scheduled",
            "completion_reported",
            "closed",
            "cancelled",
            "approval_required",
            "draft",
        ]
    )
    assert "action_required" not in statuses

    (visit,) = _by_equipment(items, "equipment_1")
    assert visit.pending_decision is not None
    assert visit.pending_decision.kind == "visit_proposal"
    assert visit.pending_decision.amount_minor == 350000
    assert visit.pending_decision.respond_by is not None
    assert visit.pending_decision.respond_by > now + timedelta(hours=20)

    (changed,) = _by_equipment(items, "equipment_4")
    assert changed.pending_decision is not None
    assert changed.pending_decision.kind == "visit_proposal"
    assert changed.pending_decision.amount_minor == 420000
    proposals = await requests.list_visit_proposals(MANAGER, ids.decode("request", changed.id))
    assert sorted((p["version"], p["status"]) for p in proposals) == [
        (1, "superseded"),
        (2, "pending"),
    ]

    (search,) = _by_equipment(items, "equipment_3")
    assert search.status == "searching"
    assert search.pending_decision is not None
    assert search.pending_decision.kind == "offers"
    assert search.pending_decision.offers_count == 3
    assert search.pending_decision.amount_minor == 200000

    (repair,) = _by_equipment(items, "equipment_6")
    assert repair.status == "in_progress"
    assert repair.pending_decision is not None
    assert repair.pending_decision.kind == "repair_quote"
    assert repair.pending_decision.amount_minor == 670000
    (quote,) = await requests.list_repair_quotes(MANAGER, ids.decode("request", repair.id))
    assert quote["price"] == {
        "amount_minor": 670000,
        "currency": "RUB",
        "vat_mode": "included",
        "zero_cost_reason": None,
        "is_known": True,
    }
    assert quote["items"] == [
        {"title": "Пусковое реле", "amount_minor": 190000},
        {"title": "Заправка фреоном", "amount_minor": 380000},
        {"title": "Работа", "amount_minor": 100000},
    ]

    (reported,) = _by_equipment(items, "equipment_7")
    assert reported.pending_decision is not None
    assert reported.pending_decision.kind == "completion_reported"

    (approval,) = [item for item in items if item.status == "approval_required"]
    assert approval.pending_decision is not None
    assert approval.pending_decision.kind == "approval"


async def test_search_offers_include_price_after_inspection() -> None:
    await seed.run()
    (search,) = _by_equipment(await _list(MANAGER), "equipment_3")

    offers = await requests.list_offers(MANAGER, ids.decode("request", search.id))

    assert len({offer.provider_organization_id for offer in offers}) == 3
    assert sorted(offer.price.amount_minor or 0 for offer in offers) == [0, 200000, 400000]
    assert [o.price.is_known for o in offers].count(False) == 1
    assert all(offer.valid_until > utcnow() + timedelta(hours=20) for offer in offers)


async def test_manager_sees_candidate_and_provider_questions() -> None:
    await seed.run()

    pending = await requests.pending_approvals(MANAGER)

    kinds = [item.kind for item in pending]
    assert kinds.count("question") == 3
    assert "draft_approval" in kinds
    assert any(item.kind == "question" and item.thread_provider_id for item in pending)


async def test_completion_report_has_before_and_after_photos() -> None:
    await seed.run()
    (reported,) = _by_equipment(await _list(MANAGER), "equipment_7")

    attachments = await files.list_for_request(MANAGER, ids.decode("request", reported.id))

    assert sorted(a.slot for a in attachments if a.slot) == ["after", "before"]


async def test_employee_sees_own_location_draft_and_approval() -> None:
    await seed.run()

    items = await _list(EMPLOYEE)

    statuses = {item.status for item in items}
    assert {"draft", "approval_required"} <= statuses
    assert all(
        item.location_id == ids.encode("location", seed._id("location:customer:1"))
        for item in items
    )


@pytest.mark.parametrize("actor", [PROVIDER_ADMIN, PROVIDER_DISPATCHER])
async def test_provider_inbox_from_two_customers_with_contracts(actor: UserActor) -> None:
    await seed.run()

    inbox = await _list(actor, assignment_states=["pending"])

    assert len(inbox) == 3
    assert {item.status for item in inbox} == {"awaiting_provider"}
    assert {item.contract_number for item in inbox} == {"Д-2026/001", "Д-2026/014"}
    assert len({item.customer_org_name for item in inbox}) == 2
    assert any(item.urgency == "urgent" for item in inbox)


async def test_provider_clarification_waits_for_customer_answer() -> None:
    await seed.run()
    (item,) = _by_equipment(await _list(PROVIDER_ADMIN), "equipment_8")

    messages, _ = await requests.list_messages(PROVIDER_ADMIN, ids.decode("request", item.id))

    assert item.status == "awaiting_provider"
    assert [m.author_kind for m in messages] == ["provider_membership"]


async def test_provider_work_tab_has_agreed_visit() -> None:
    await seed.run()

    work = await _list(PROVIDER_ADMIN, assignment_states=["accepted"])

    statuses = sorted(item.status for item in work)
    assert statuses == sorted(
        ["accepted", "accepted", "scheduled", "in_progress", "completion_reported"]
    )
    (scheduled,) = [item for item in work if item.status == "scheduled"]
    proposals = await requests.list_visit_proposals(
        PROVIDER_ADMIN, ids.decode("request", scheduled.id)
    )
    (agreed,) = [p for p in proposals if p["status"] == "approved"]
    assert agreed["visit_window_start"] is not None


async def test_marketplace_shows_offer_counts() -> None:
    await seed.run()

    cards, _ = await requests.list_marketplace_requests(PROVIDER_ADMIN, limit=50)

    counts = sorted(card.offers_count for card in cards)
    assert counts == [0, 3]
    (open_question,) = [card for card in cards if card.has_open_question]
    assert open_question.offers_count == 0


async def test_second_run_does_not_duplicate_scenarios() -> None:
    await seed.run()
    report = await seed.run()

    assert report.requests_created == 0
    assert await _demo_request_count() == len(scenarios.SCENARIOS)


async def test_refresh_recreates_scenarios_with_fresh_deadlines() -> None:
    await seed.run()
    before = {item.id for item in await _list(MANAGER)}
    async with db_session.transaction() as session:
        for statement in (
            "UPDATE visit_proposals SET valid_until = now() - interval '1 hour'",
            "UPDATE repair_quotes SET valid_until = now() - interval '1 hour'",
            "UPDATE offers SET valid_until = now() - interval '1 hour'",
        ):
            await session.execute(text(statement))
    (stale,) = _by_equipment(await _list(MANAGER), "equipment_1")
    assert stale.pending_decision is None

    report = await seed.refresh()

    assert report.organizations == 0
    assert report.users == 0
    assert report.requests_created == len(scenarios.SCENARIOS)
    assert await _demo_request_count() == len(scenarios.SCENARIOS)
    items = await _list(MANAGER)
    assert not before & {item.id for item in items}
    (visit,) = _by_equipment(items, "equipment_1")
    assert visit.pending_decision is not None
    assert visit.pending_decision.respond_by is not None
    assert visit.pending_decision.respond_by > utcnow() + timedelta(hours=20)
    (search,) = _by_equipment(items, "equipment_3")
    assert search.pending_decision is not None
    assert search.pending_decision.offers_count == 3


async def test_refresh_then_full_reset_leaves_no_demo_rows() -> None:
    await seed.run()
    await seed.refresh()
    await seed.reset()

    assert await _demo_request_count() == 0


async def test_scenarios_survive_half_a_day_of_background_expiry() -> None:
    await seed.run()
    before = sorted(item.status for item in await _list(MANAGER))

    await requests.expire_due(utcnow() + timedelta(hours=12))

    items = await _list(MANAGER)
    assert sorted(item.status for item in items) == before
    (visit,) = _by_equipment(items, "equipment_1")
    assert visit.pending_decision is not None
