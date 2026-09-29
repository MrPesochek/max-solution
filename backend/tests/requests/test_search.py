import asyncio

import pytest

from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.db.enums import OfferStatus, PublicCardStatus
from app.db.models import Assignment, Offer, RequestPublicCard
from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")

_SENSITIVE = ("ул. Примерная", "+70000000000", "SN-0001", "Кафе на Ленина", "Дежурный")


def _json(value: object) -> str:
    return str(value)


async def test_a07_publication_discloses_only_white_list(world: World) -> None:
    published = await h.make_published(world)
    card = published["search"]["public_card"]
    assert published["status"] == "searching"
    assert published["search"]["matched_providers"] == 1
    assert card["brand"] == "Полюс"
    assert card["model"] == "ВХС-1"
    assert card["published_description"] == "Не держит температуру"
    assert set(card) == {
        "request_id",
        "request_number",
        "equipment_category_id",
        "equipment_category_name",
        "brand",
        "model",
        "city_id",
        "district_id",
        "city_name",
        "district_name",
        "city_timezone",
        "urgency",
        "published_description",
        "published_attachment_ids",
        "status",
        "published_at",
        "search_expires_at",
    }

    events = await h.integration_events()
    assert [event.event_type for event in events] == ["marketplace.request.available"]
    assert events[0].recipient_org_id == world.provider_org_id
    body = _json(events[0].payload)
    assert all(secret not in body for secret in _SENSITIVE)
    assert "public_card" in events[0].payload

    cards, _ = await api.list_marketplace_requests(world.dispatcher)
    assert [item.request_id for item in cards] == [published["id"]]
    with pytest.raises(NotFound):
        await api.get_request(world.dispatcher, h.rid(published))


async def test_a07_foreign_provider_does_not_see_the_card(world: World, other_world: World) -> None:
    published = await h.make_published(world)
    cards, _ = await api.list_marketplace_requests(other_world.dispatcher)
    assert cards == []
    with pytest.raises(NotFound):
        await api.get_marketplace_card(other_world.dispatcher, h.rid(published))
    with pytest.raises(NotFound):
        await api.submit_offer(
            other_world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1000)
        )


async def test_preview_does_not_change_state(world: World) -> None:
    draft = await h.make_marketplace_draft(world)
    preview = await api.preview_public_card(
        world.manager,
        h.rid(draft),
        data=api.PublicCardInput(published_description="Витрина не морозит"),
    )
    assert preview.matched_providers == 1
    assert preview.public_card.published_description == "Витрина не морозит"
    assert "location.address" in preview.withheld_fields
    assert preview.existing_binding is not None
    assert preview.existing_binding.status == "confirmed"

    view = await api.get_request(world.manager, h.rid(draft))
    assert view.status == "draft"
    assert view.version == draft["version"]
    assert await h.count_of(RequestPublicCard) == 0


async def test_s5_no_matching_providers() -> None:
    empty_world = await h.build_world_without_providers()
    draft = await h.make_marketplace_draft(empty_world)
    result = (
        await api.publish_search(
            empty_world.manager, h.rid(draft), expected_version=draft["version"]
        )
    ).body
    assert result["status"] == "action_required"
    assert result["search"]["published"] is False
    assert result["search"]["matched_providers"] == 0
    types = await h.notification_types()
    assert "search.no_providers" in types


async def test_employee_cannot_publish(world: World) -> None:
    draft = await h.make_marketplace_draft(world)
    with pytest.raises(Forbidden):
        await api.publish_search(world.employee, h.rid(draft))


async def test_offer_lifecycle_and_comparison(world: World) -> None:
    published = await h.make_published(world)
    first = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                amount_minor=150000, currency="RUB", scope_description="Выезд и диагностика"
            ),
            expected_version=published["version"],
        )
    ).body
    assert first["version"] == 1
    assert first["state"] == "active"

    second = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(amount_minor=120000, currency="RUB"),
        )
    ).body
    assert second["version"] == 2
    old = await h.reload(Offer, h.oid(first))
    assert old.state == OfferStatus.CLOSED
    assert old.superseded_by_offer_id == h.oid(second)

    offers = await api.list_offers(world.manager, h.rid(published))
    assert [offer.version for offer in offers] == [1, 2]
    assert all(offer.provider is not None for offer in offers)
    assert {offer.provider.display_name for offer in offers if offer.provider} == {"Холод-Сервис"}
    assert all(offer.provider.verification_marks == [] for offer in offers if offer.provider)
    assert all(offer.provider.unique_reviewer_orgs_count == 0 for offer in offers if offer.provider)

    own_offers = await api.list_offers(world.dispatcher, h.rid(published))
    assert all(offer.provider is None for offer in own_offers)

    assert await api.list_offers(world.employee, h.rid(published))
    with pytest.raises(Forbidden):
        await api.select_offer(world.employee, h.rid(published), offer_id=h.oid(second))

    withdrawn = (
        await api.withdraw_offer(world.dispatcher, h.rid(published), offer_id=h.oid(second))
    ).body
    assert withdrawn["state"] == "withdrawn"
    with pytest.raises(Conflict) as exc:
        await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(second))
    assert exc.value.code == "OFFER_NOT_ACTIVE"


async def test_a08_selection_is_not_cost_approval(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(amount_minor=None, comment="Стоимость уточним на месте"),
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    assert selected["status"] == "awaiting_assignment_confirmation"
    assert selected["assignment"]["state"] == "pending"
    assert selected["assignment"]["expires_at"] is not None

    events = await h.integration_events()
    selected_events = [e for e in events if e.event_type == "offer.selected"]
    assert len(selected_events) == 1
    assert selected_events[0].payload["request"]["contacts_disclosed"] is False
    assert selected_events[0].payload["request"]["location"]["address"] is None

    confirmed = (
        await api.accept_assignment(
            world.dispatcher,
            h.rid(published),
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    assert confirmed["status"] == "accepted"
    assert confirmed["contacts_disclosed"] is True
    assert confirmed["location"]["address"] == "ул. Примерная, 1"
    assert confirmed["visit_proposals"] == []


async def test_complete_offer_schedules_visit_at_once(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                visit_window_start=h.window_start(),
                visit_window_end=h.window_end(),
                amount_minor=200000,
                currency="RUB",
                scope_description="Выезд, диагностика",
            ),
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    confirmed = (
        await api.accept_assignment(
            world.dispatcher,
            h.rid(published),
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    assert confirmed["status"] == "scheduled"
    assert confirmed["visit_proposals"][0]["status"] == "approved"
    assert confirmed["visit_proposals"][0]["price"]["amount_minor"] == 200000

    card = await h.public_card(published)
    assert card.status == PublicCardStatus.CLOSED


async def test_losing_offers_are_closed_without_details(world: World) -> None:
    published, rival = await h.make_published_with_rival(world)
    mine = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                visit_window_start=h.window_start(),
                visit_window_end=h.window_end(),
                amount_minor=100000,
                currency="RUB",
                scope_description="Выезд",
            ),
        )
    ).body
    rival_offer = (
        await api.submit_offer(
            rival.dispatcher,
            h.rid(published),
            data=api.OfferInput(amount_minor=999000, currency="RUB", comment="Дорого"),
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(mine))).body
    await api.accept_assignment(
        world.dispatcher,
        h.rid(published),
        assignment_id=h.assignment_id(selected),
        expected_version=selected["version"],
    )

    losing = await h.reload(Offer, h.oid(rival_offer))
    assert losing.state == OfferStatus.CLOSED
    closed_events = [
        event
        for event in await h.integration_events()
        if event.event_type == "marketplace.request.closed"
    ]
    assert len(closed_events) == 1
    assert closed_events[0].recipient_org_id == rival.provider_org_id
    body = _json(closed_events[0].payload)
    assert "999000" not in body and "100000" not in body
    assert all(secret not in body for secret in _SENSITIVE)

    cards, _ = await api.list_marketplace_requests(rival.dispatcher)
    assert cards == []
    with pytest.raises(NotFound):
        await api.get_request(rival.dispatcher, h.rid(published))

    own = await api.list_offers(rival.dispatcher, h.rid(published))
    assert [offer.id for offer in own] == [rival_offer["id"]]
    winner_offers = await api.list_offers(world.dispatcher, h.rid(published))
    assert [offer.id for offer in winner_offers] == [mine["id"]]
    assert len(await api.list_offers(world.manager, h.rid(published))) == 2


async def test_a10_expired_offer_cannot_be_selected(world: World, clock) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher,
            h.rid(published),
            data=api.OfferInput(
                amount_minor=100000, currency="RUB", valid_until=clock.now + h.hours(2)
            ),
        )
    ).body
    clock.advance(hours=3)
    with pytest.raises(Conflict) as exc:
        await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))
    assert exc.value.code == "OFFER_EXPIRED"

    assert (await h.reload(Offer, h.oid(offer))).state == OfferStatus.EXPIRED
    counters = await api.expire_due()
    assert counters["offers"] == 0


async def test_a10_reservation_expires_and_frees_the_slot(world: World, clock) -> None:
    published = await h.make_published(world)
    first = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(first))).body

    clock.advance(hours=3)
    counters = await api.expire_due()
    assert counters["reservations"] == 1

    view = await api.get_request(world.manager, h.rid(published))
    assert view.status == "searching"
    assert (await h.reload(Assignment, h.assignment_id(selected))).state == "expired"
    assert (await h.reload(Offer, h.oid(first))).state == OfferStatus.CLOSED
    assert "assignment.expired" in await h.notification_types()


async def test_s5_search_window_closes_without_offers(world: World, clock) -> None:
    published = await h.make_published(world)
    clock.advance(hours=25)
    counters = await api.expire_due()
    assert counters["searches"] == 1

    view = await api.get_request(world.manager, h.rid(published))
    assert view.status == "action_required"
    card = await h.public_card(published)
    assert card.status == PublicCardStatus.CLOSED
    assert "search.expired" in await h.notification_types()


async def test_decline_of_reservation_returns_to_search(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body
    declined = (
        await api.decline_assignment(
            world.dispatcher,
            h.rid(published),
            assignment_id=h.assignment_id(selected),
            reason="Занят",
            expected_version=selected["version"],
        )
    ).body
    assert declined["status"] == "searching"
    assert (await h.reload(Offer, h.oid(offer))).state == OfferStatus.CLOSED


async def test_a09_parallel_select_offer(world: World) -> None:
    published, rival = await h.make_published_with_rival(world)
    mine = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    theirs = (
        await api.submit_offer(
            rival.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=110000)
        )
    ).body

    results = await asyncio.gather(
        api.select_offer(world.manager, h.rid(published), offer_id=h.oid(mine)),
        api.select_offer(world.manager, h.rid(published), offer_id=h.oid(theirs)),
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, DomainError)]
    assert len(ok) == 1
    assert len(failed) == 1
    assert failed[0].code in {"ASSIGNMENT_ALREADY_ACTIVE", "INVALID_TRANSITION", "OFFER_NOT_ACTIVE"}
    assert await h.count_of(Assignment) == 1
    selected = [
        offer
        for offer in await api.list_offers(world.manager, h.rid(published))
        if offer.state == OfferStatus.SELECTED
    ]
    assert len(selected) == 1


async def test_s3_5_private_dialog_before_assignment(world: World) -> None:
    published, rival = await h.make_published_with_rival(world)
    question = (
        await api.post_message(world.dispatcher, h.rid(published), body="Есть ли доступ ночью?")
    ).body
    assert question["id"]

    answer = await api.post_message(
        world.manager,
        h.rid(published),
        body="Да, сторож откроет",
        thread_provider_org_id=world.provider_org_id,
    )
    assert answer.status == 201

    mine, _ = await api.list_messages(world.dispatcher, h.rid(published))
    assert [m.body for m in mine] == ["Есть ли доступ ночью?", "Да, сторож откроет"]

    theirs, _ = await api.list_messages(rival.dispatcher, h.rid(published))
    assert theirs == []

    customer_view, _ = await api.list_messages(world.manager, h.rid(published))
    assert len(customer_view) == 2
    view = await api.get_request(world.manager, h.rid(published))
    assert view.version == published["version"]


async def test_cancel_during_search_closes_card(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    cancelled = (
        await api.request_cancellation(
            world.manager, h.rid(published), target="cancel_request", reason="Не требуется"
        )
    ).body
    assert cancelled["status"] == "cancelled"
    assert (await h.reload(Offer, h.oid(offer))).state == OfferStatus.CLOSED
    assert (await h.public_card(published)).status == "closed"
    assert "marketplace.request.closed" in await h.event_types()


async def test_route_change_back_and_forth(world: World) -> None:
    submitted = await h.make_submitted(world)
    declined = (
        await api.decline_assignment(
            world.dispatcher,
            h.rid(submitted),
            assignment_id=h.assignment_id(submitted),
            reason="Нет мастера",
            expected_version=submitted["version"],
        )
    ).body
    published = (
        await api.publish_search(
            world.manager, h.rid(submitted), expected_version=declined["version"]
        )
    ).body
    assert published["status"] == "searching"
    assert published["route"] == "marketplace"

    changed = (
        await api.request_cancellation(
            world.manager, h.rid(submitted), target="change_provider", reason="Вернёмся к своим"
        )
    ).body
    assert changed["status"] == "action_required"
    assert (await h.public_card(published)).status == "closed"
    back = (
        await api.submit_to_own_service(
            world.manager, h.rid(submitted), expected_version=changed["version"]
        )
    ).body
    assert back["status"] == "awaiting_provider"

    cancelled = (
        await api.request_cancellation(
            world.manager, h.rid(submitted), target="cancel_request", reason="Не требуется"
        )
    ).body
    assert cancelled["status"] == "cancelled"

    followup = (await api.create_followup_request(world.manager, h.rid(submitted))).body
    assert followup["status"] == "draft"
    assert followup["id"] != submitted["id"]
    resubmitted = (
        await api.submit_to_own_service(
            world.manager, h.rid(followup), expected_version=followup["version"]
        )
    ).body
    assert resubmitted["status"] == "awaiting_provider"


async def test_integration_client_needs_marketplace_scope(world: World) -> None:
    from app.core.actor import IntegrationActor

    published = await h.make_published(world)
    limited = IntegrationActor(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.provider_org_id,
        scopes=frozenset({"requests:read", "requests:write"}),
    )
    with pytest.raises(Forbidden) as exc:
        await api.submit_offer(limited, h.rid(published), data=api.OfferInput(amount_minor=1000))
    assert exc.value.details["required_scope"] == "marketplace:write"

    full = IntegrationActor(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.provider_org_id,
        scopes=frozenset({"marketplace:read", "marketplace:write"}),
    )
    offer = (
        await api.submit_offer(full, h.rid(published), data=api.OfferInput(amount_minor=1000))
    ).body
    assert offer["state"] == "active"
    cards, _ = await api.list_marketplace_requests(full)
    assert len(cards) == 1
