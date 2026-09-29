from typing import Any

import pytest

from app.core import ids
from app.core.errors import NotFound
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _employee_marketplace_draft(world: World) -> dict[str, Any]:
    result = await api.create_draft(
        world.employee, equipment_id=world.equipment_id, route="marketplace"
    )
    return result.body


async def test_list_item_carries_equipment_details(world: World) -> None:
    submitted = await h.make_submitted(world)
    customer_items, _ = await api.list_requests(world.manager)
    item = next(i for i in customer_items if i.id == submitted["id"])
    assert item.equipment_id == ids.encode("equipment", world.equipment_id)
    assert item.equipment_brand == "Полюс"
    assert item.equipment_category_name
    assert item.equipment_category_name == submitted["equipment"]["category_name"]

    provider_items, _ = await api.list_requests(world.dispatcher)
    assert provider_items[0].equipment_category_name == item.equipment_category_name
    assert provider_items[0].equipment_brand == "Полюс"

    card = await api.get_request(world.manager, h.rid(submitted))
    assert card.equipment_category_name == item.equipment_category_name  # type: ignore[union-attr]
    provider_card = await api.get_request(world.dispatcher, h.rid(submitted))
    assert provider_card.equipment_category_name == item.equipment_category_name  # type: ignore[union-attr]


async def test_pending_decision_only_for_manager(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.propose_visit(
        world.dispatcher,
        h.rid(accepted),
        assignment_id=h.assignment_id(accepted),
        data=api.VisitProposalInput(**h.visit_window(), amount_minor=250000, currency="RUB"),
        expected_version=accepted["version"],
    )
    draft = await _employee_marketplace_draft(world)
    await api.request_approval(world.employee, h.rid(draft), expected_version=draft["version"])
    published = await h.make_published(world)
    await api.submit_offer(
        world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=90000)
    )

    items, _ = await api.list_requests(world.manager)
    by_id = {item.id: item.pending_decision for item in items}
    visit = by_id[accepted["id"]]
    assert visit is not None
    assert (visit.kind, visit.amount_minor, visit.currency) == ("visit_proposal", 250000, "RUB")
    assert visit.respond_by is not None
    approval = by_id[draft["id"]]
    assert approval is not None and approval.kind == "approval"
    offers = by_id[published["id"]]
    assert offers is not None
    assert (offers.kind, offers.offers_count, offers.amount_minor) == ("offers", 1, 90000)

    employee_items, _ = await api.list_requests(world.employee)
    assert all(item.pending_decision is None for item in employee_items)

    aggregate = {item.kind: item for item in await api.pending_approvals(world.manager)}
    assert (aggregate["visit_proposal"].amount_minor, aggregate["visit_proposal"].currency) == (
        250000,
        "RUB",
    )


async def test_approver_name_for_draft_on_approval(world: World) -> None:
    draft = await _employee_marketplace_draft(world)
    before = await api.get_request(world.employee, h.rid(draft))
    assert before.approver_name is None  # type: ignore[union-attr]

    result = await api.request_approval(
        world.employee, h.rid(draft), expected_version=draft["version"]
    )
    assert result.body["approver_name"] == "Руководитель"
    card = await api.get_request(world.employee, h.rid(draft))
    assert card.approver_name == "Руководитель"  # type: ignore[union-attr]


async def test_unread_messages_count_and_mark_read(world: World) -> None:
    submitted = await h.make_submitted(world)
    request_id = h.rid(submitted)
    assignment = h.assignment_id(submitted)
    await api.post_message(
        world.dispatcher, request_id, body="Будем завтра", assignment_id=assignment
    )
    await api.post_message(
        world.dispatcher, request_id, body="С 10 до 12", assignment_id=assignment
    )
    await api.post_message(world.manager, request_id, body="Хорошо")

    manager_card = await api.get_request(world.manager, request_id)
    assert manager_card.unread_messages_count == 2  # type: ignore[union-attr]
    dispatcher_card = await api.get_request(world.dispatcher, request_id)
    assert dispatcher_card.unread_messages_count == 1  # type: ignore[union-attr]

    marked = await api.mark_messages_read(world.manager, request_id)
    assert marked.body["unread_messages_count"] == 0
    again = await api.mark_messages_read(world.manager, request_id)
    assert again.body == marked.body

    assert (await api.get_request(world.manager, request_id)).unread_messages_count == 0  # type: ignore[union-attr]
    assert (await api.get_request(world.employee, request_id)).unread_messages_count == 3  # type: ignore[union-attr]

    await api.post_message(
        world.dispatcher, request_id, body="Уже выехали", assignment_id=assignment
    )
    assert (await api.get_request(world.manager, request_id)).unread_messages_count == 1  # type: ignore[union-attr]


async def test_mark_read_respects_access(world: World, other_world: World) -> None:
    submitted = await h.make_submitted(world)
    with pytest.raises(NotFound):
        await api.mark_messages_read(other_world.manager, h.rid(submitted))
    with pytest.raises(NotFound):
        await api.mark_messages_read(other_world.dispatcher, h.rid(submitted))
    with pytest.raises(NotFound):
        await api.mark_messages_read(world.other_employee, h.rid(submitted))
