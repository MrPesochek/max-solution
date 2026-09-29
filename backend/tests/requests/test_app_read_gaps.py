from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import InvalidTransition, NotFound, ValidationFailed
from app.db import session as db_session
from app.db.models import (
    IntegrationClient,
    IntegrationEvent,
    Organization,
    ServiceBinding,
    WebhookDelivery,
    WebhookSubscription,
)
from app.modules.requests import api
from app.modules.requests.views import RequestCustomerView, RequestProviderView
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _customer_card(world: World, body: dict[str, object]) -> RequestCustomerView:
    view = await api.get_request(world.manager, h.rid(body))
    assert isinstance(view, RequestCustomerView)
    return view


async def _set_provider_phone(world: World, phone: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(Organization)
            .where(Organization.id == world.provider_org_id)
            .values(contact_phone=phone)
        )


async def _assigned_event(request_body: dict[str, object]) -> IntegrationEvent:
    events = await h.integration_events(h.rid(request_body))
    return next(e for e in events if e.event_type == "request.assigned")


async def _subscription(world: World) -> WebhookSubscription:
    async with db_session.transaction() as session:
        client_id = world.integration.integration_client_id
        subscription = WebhookSubscription(
            integration_client_id=client_id,
            provider_org_id=world.provider_org_id,
            url="https://crm.example/hook",
            event_types=["request.assigned"],
            secret_encrypted=b"secret",
        )
        session.add(subscription)
        await session.flush()
        return subscription


async def test_delivery_without_crm_is_none_in_app(world: World) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(IntegrationClient)
            .where(IntegrationClient.provider_org_id == world.provider_org_id)
            .values(status="revoked")
        )
    submitted = await h.make_submitted(world)
    card = await _customer_card(world, submitted)
    assert card.delivery is not None
    assert card.delivery.state == "none"
    assert card.delivery.channel == "app"


async def test_delivery_follows_webhook_attempts_without_error_details(world: World) -> None:
    submitted = await h.make_submitted(world)
    card = await _customer_card(world, submitted)
    assert card.delivery is not None
    assert (card.delivery.state, card.delivery.channel) == ("none", "app")

    event = await _assigned_event(submitted)
    subscription = await _subscription(world)
    card = await _customer_card(world, submitted)
    assert card.delivery is not None
    assert (card.delivery.state, card.delivery.channel) == ("queued", "crm")
    now = utcnow()
    async with db_session.transaction() as session:
        delivery = WebhookDelivery(
            integration_event_id=event.id,
            webhook_subscription_id=subscription.id,
            provider_org_id=world.provider_org_id,
            state="retrying",
            attempt_count=2,
            last_attempt_at=now,
            next_attempt_at=now + timedelta(minutes=5),
            last_http_status=500,
            last_error="upstream said: db password wrong",
            expires_at=now + timedelta(days=1),
        )
        session.add(delivery)
        await session.flush()
        delivery_id = delivery.id

    card = await _customer_card(world, submitted)
    assert card.delivery is not None
    assert card.delivery.state == "retrying"
    assert card.delivery.next_attempt_at is not None
    dumped = card.model_dump_json()
    assert "password" not in dumped
    assert "crm.example" not in dumped

    async with db_session.transaction() as session:
        await session.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id)
            .values(state="failed", next_attempt_at=None)
        )
    card = await _customer_card(world, submitted)
    assert card.delivery is not None and card.delivery.state == "failed"

    async with db_session.transaction() as session:
        await session.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id)
            .values(state="delivered", last_error=None)
        )
    card = await _customer_card(world, submitted)
    assert card.delivery is not None
    assert card.delivery.state == "delivered"
    assert card.delivery.delivered_at is not None


async def test_draft_has_no_delivery(world: World) -> None:
    draft = await h.make_draft(world)
    card = await _customer_card(world, draft)
    assert card.delivery is None


async def test_provider_phone_only_after_disclosure(world: World) -> None:
    await _set_provider_phone(world, "+74950000001")
    rival = await factories.build_rival_provider(world)
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            rival.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=150000)
        )
    ).body
    selected = (
        await api.select_offer(
            world.manager,
            h.rid(published),
            offer_id=h.oid(offer),
            offer_version=offer["version"],
            expected_version=(await _customer_card(world, published)).version,
        )
    ).body
    assert selected["assignment"]["provider_contact_phone"] is None

    async with db_session.transaction() as session:
        await session.execute(
            update(Organization)
            .where(Organization.id == rival.provider_org_id)
            .values(contact_phone="+74950000002")
        )
    await api.accept_assignment(
        rival.dispatcher,
        h.rid(selected),
        assignment_id=h.assignment_id(selected),
        expected_version=selected["version"],
    )
    card = await _customer_card(world, selected)
    assert card.assignment is not None
    assert card.assignment.provider_contact_phone == "+74950000002"


async def test_own_service_phone_is_known_right_away(world: World) -> None:
    await _set_provider_phone(world, "+74950000001")
    submitted = await h.make_submitted(world)
    assert submitted["assignment"]["provider_contact_phone"] == "+74950000001"


async def test_candidate_dialog_is_private_and_needs_answer(world: World) -> None:
    rival = await factories.build_rival_provider(world)
    published = await h.make_published(world)
    request_id = h.rid(published)
    offer = (
        await api.submit_offer(world.dispatcher, request_id, data=api.OfferInput(amount_minor=1))
    ).body
    question = await api.post_dialog_message(
        world.dispatcher, request_id, body="Есть ли доступ ночью?"
    )
    assert question.body["thread_provider_id"] == ids.encode("organization", world.provider_org_id)

    for actor in (world.manager, world.employee):
        kinds = [item.kind for item in await api.pending_approvals(actor)]
        assert "question" in kinds
    assert await api.pending_approvals(world.other_employee) == []

    thread, _ = await api.list_dialog_messages(world.employee, request_id, offer_id=h.oid(offer))
    assert [m.body for m in thread] == ["Есть ли доступ ночью?"]
    answer = await api.post_dialog_message(
        world.employee, request_id, body="Да, сторож откроет", offer_id=h.oid(offer)
    )
    assert answer.status == 201

    questions = [i for i in await api.pending_approvals(world.manager) if i.kind == "question"]
    assert questions == []
    mine, _ = await api.list_dialog_messages(world.dispatcher, request_id)
    assert [m.body for m in mine] == ["Есть ли доступ ночью?", "Да, сторож откроет"]
    theirs, _ = await api.list_dialog_messages(rival.dispatcher, request_id)
    assert theirs == []

    cards, _ = await api.list_marketplace_requests(world.dispatcher)
    assert cards[0].has_clarification is True
    assert cards[0].has_open_question is False
    rival_cards, _ = await api.list_marketplace_requests(rival.dispatcher)
    assert rival_cards[0].offers_count == 1
    assert rival_cards[0].has_clarification is False


async def test_customer_cannot_use_foreign_offer_thread(world: World) -> None:
    published = await h.make_published(world)
    other = await h.make_published(world)
    offer = (
        await api.submit_offer(world.dispatcher, h.rid(other), data=api.OfferInput(amount_minor=1))
    ).body
    with pytest.raises(NotFound):
        await api.list_dialog_messages(world.manager, h.rid(published), offer_id=h.oid(offer))
    with pytest.raises(NotFound):
        await api.list_dialog_messages(world.other_employee, h.rid(other), offer_id=h.oid(offer))


async def test_dialog_closes_after_selection(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1)
        )
    ).body
    await api.select_offer(
        world.manager,
        h.rid(published),
        offer_id=h.oid(offer),
        offer_version=offer["version"],
        expected_version=(await _customer_card(world, published)).version,
    )
    with pytest.raises(InvalidTransition) as info:
        await api.post_dialog_message(
            world.manager, h.rid(published), body="Ещё вопрос", offer_id=h.oid(offer)
        )
    assert info.value.code == "OFFER_DIALOG_CLOSED"


async def test_open_question_in_marketplace_list(world: World) -> None:
    published = await h.make_published(world)
    await api.post_dialog_message(world.dispatcher, h.rid(published), body="Какой этаж?")
    cards, _ = await api.list_marketplace_requests(world.dispatcher)
    assert cards[0].has_open_question is True
    assert cards[0].offers_count == 0


async def test_question_after_assignment_needs_answer(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.post_message(
        world.dispatcher,
        h.rid(accepted),
        body="Нужен пропуск?",
        assignment_id=h.assignment_id(accepted),
    )
    items = await api.pending_approvals(world.employee)
    assert [(i.kind, i.request.id, i.thread_provider_id) for i in items] == [
        ("question", accepted["id"], None)
    ]
    await api.post_message(world.employee, h.rid(accepted), body="Нет")
    assert await api.pending_approvals(world.employee) == []


async def _quote(world: World, data: api.RepairQuoteInput) -> dict[str, object]:
    accepted = await h.make_accepted(world)
    result = await api.create_repair_quote(
        world.dispatcher,
        h.rid(accepted),
        assignment_id=h.assignment_id(accepted),
        data=data,
        expected_version=accepted["version"],
    )
    return result.body


async def test_quote_items_sum_is_checked(world: World) -> None:
    items = (
        api.RepairQuoteItemInput("Компрессор", 400000),
        api.RepairQuoteItemInput("Работа", 100000),
    )
    body = await _quote(
        world,
        api.RepairQuoteInput(description_of_work="Замена компрессора", currency="RUB", items=items),
    )
    quote = body["repair_quotes"][0]  # type: ignore[index]
    assert quote["price"]["amount_minor"] == 500000
    assert quote["items"] == [
        {"title": "Компрессор", "amount_minor": 400000},
        {"title": "Работа", "amount_minor": 100000},
    ]
    customer = await _customer_card(world, body)
    assert [i.title for i in customer.repair_quotes[0].items] == ["Компрессор", "Работа"]

    with pytest.raises(ValidationFailed) as info:
        await _quote(
            world,
            api.RepairQuoteInput(
                description_of_work="Замена", amount_minor=1, currency="RUB", items=items
            ),
        )
    assert info.value.code == "QUOTE_ITEMS_SUM_MISMATCH"


async def test_quote_without_items_keeps_single_amount(world: World) -> None:
    body = await _quote(
        world,
        api.RepairQuoteInput(description_of_work="Ремонт", amount_minor=9900, currency="RUB"),
    )
    assert body["repair_quotes"][0]["items"] == []  # type: ignore[index]


async def test_history_names_people_of_own_side_and_orgs_of_other(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.set_external_reference(
        world.integration,
        h.rid(accepted),
        external_id="CRM-1",
        expected_version=accepted["version"],
    )
    customer, _ = await api.request_history(world.manager, h.rid(accepted))
    names = {e.event_type: e.actor_display_name for e in customer}
    assert names["RequestSubmittedToOwnService"] == "Сотрудник"
    assert names["AssignmentAccepted"] == "Холод-Сервис"
    assert names["ExternalReferenceLinked"] == "CRM Холод-Сервис"

    provider, _ = await api.request_history(world.dispatcher, h.rid(accepted))
    names = {e.event_type: e.actor_display_name for e in provider}
    assert names["AssignmentAccepted"] == "Диспетчер"
    assert names["RequestSubmittedToOwnService"] == "Сеть кафе"


async def test_provider_list_shows_customer_and_contract(world: World) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(ServiceBinding)
            .where(ServiceBinding.id == world.binding_id)
            .values(claimed_contract_number="Д-17/2026")
        )
    submitted = await h.make_submitted(world)
    items, _ = await api.list_requests(world.dispatcher)
    assert [(i.id, i.customer_org_name, i.contract_number) for i in items] == [
        (submitted["id"], "Сеть кафе", "Д-17/2026")
    ]
    mine, _ = await api.list_requests(world.manager)
    assert mine[0].customer_org_name is None
    assert mine[0].contract_number is None


async def test_marketplace_card_hides_customer(world: World) -> None:
    await h.make_published(world)
    cards, _ = await api.list_marketplace_requests(world.dispatcher)
    dumped = cards[0].model_dump_json()
    assert "Сеть кафе" not in dumped
    assert "customer_org_name" not in dumped


async def test_completion_report_in_both_views(world: World) -> None:
    reported = await h.make_completion_reported(world)
    customer = await _customer_card(world, reported)
    assert customer.completion_report is not None
    assert customer.completion_report.outcome == "resolved"
    assert customer.completion_report.summary == "Заменён термостат"
    provider = await api.get_request(world.dispatcher, h.rid(reported))
    assert isinstance(provider, RequestProviderView)
    assert provider.completion_report is not None
    assert provider.completion_report.photos_before == []
