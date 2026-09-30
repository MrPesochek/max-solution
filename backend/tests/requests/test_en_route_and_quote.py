from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.db import session as db_session
from app.db.models import (
    Assignment,
    City,
    District,
    IntegrationClient,
    Membership,
    RequestEvent,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import get_settings
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


async def _mark_en_route(world: World, body: dict[str, object]) -> dict[str, object]:
    result = await api.mark_en_route(
        world.dispatcher,
        h.rid(body),
        assignment_id=h.assignment_id(body),
        expected_version=body["version"],
    )
    return result.body


async def test_mark_en_route_keeps_status_and_notifies(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    marked = await _mark_en_route(world, scheduled)

    assert marked["status"] == "scheduled"
    assert marked["assignment"]["en_route_at"] is not None
    card = await _customer_card(world, scheduled)
    assert card.status == "scheduled"
    assert card.assignment is not None and card.assignment.en_route_at is not None

    assert "field_worker.en_route" in await h.notification_types()
    events = await h.integration_events(h.rid(scheduled))
    assert events[-1].event_type == "request.changed"
    assert events[-1].payload["change_kind"] == "en_route"
    history, _ = await api.request_history(world.manager, h.rid(scheduled))
    assert history[-1].event_type == "FieldWorkerEnRoute"

    started = await api.start_work(
        world.dispatcher,
        h.rid(scheduled),
        assignment_id=h.assignment_id(scheduled),
        expected_version=marked["version"],
    )
    assert started.body["status"] == "in_progress"


async def test_mark_en_route_twice_conflicts(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    marked = await _mark_en_route(world, scheduled)
    with pytest.raises(Conflict) as exc:
        await _mark_en_route(world, marked)
    assert exc.value.code == "ALREADY_EN_ROUTE"


async def test_mark_en_route_needs_scheduled_visit(world: World) -> None:
    accepted = await h.make_accepted(world)
    with pytest.raises(InvalidTransition):
        await _mark_en_route(world, accepted)


async def test_customer_and_foreign_provider_cannot_mark_en_route(
    world: World, other_world: World
) -> None:
    scheduled = await h.make_scheduled(world)
    with pytest.raises(Forbidden):
        await api.mark_en_route(
            world.manager,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )
    with pytest.raises(NotFound):
        await api.mark_en_route(
            other_world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )


async def test_mark_en_route_integration_needs_write_scope(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    read_only = world.integration.__class__(
        integration_client_id=world.integration.integration_client_id,
        organization_id=world.integration.organization_id,
        scopes=frozenset({"requests:read"}),
    )
    with pytest.raises(Forbidden):
        await api.mark_en_route(
            read_only,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )
    marked = await api.mark_en_route(
        world.integration,
        h.rid(scheduled),
        assignment_id=h.assignment_id(scheduled),
        expected_version=scheduled["version"],
    )
    assert marked.body["assignment"]["en_route_at"] is not None


async def test_list_item_carries_visit_window_worker_and_messages(world: World) -> None:
    accepted = await h.make_accepted(world)
    request_id = h.rid(accepted)
    start, end = h.window_start(), h.window_end()
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            request_id,
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(
                visit_window_start=start, visit_window_end=end, amount_minor=1000, currency="RUB"
            ),
            expected_version=accepted["version"],
        )
    ).body
    scheduled = (
        await api.approve_visit_proposal(
            world.manager,
            request_id,
            proposal_id=h.proposal_id(proposed),
            proposal_version=proposed["visit_proposals"][0]["version"],
            expected_version=proposed["version"],
        )
    ).body
    await api.set_field_worker(
        world.dispatcher,
        request_id,
        assignment_id=h.assignment_id(scheduled),
        display_name="Андрей Ковалёв",
        expected_version=scheduled["version"],
    )
    await api.post_message(
        world.dispatcher,
        request_id,
        body="Буду к двум",
        assignment_id=h.assignment_id(scheduled),
    )

    items, _ = await api.list_requests(world.manager)
    item = next(i for i in items if i.id == scheduled["id"])
    assert item.visit_window_start == start
    assert item.visit_window_end == end
    assert item.timezone == "Europe/Moscow"
    assert item.field_worker_name == "Андрей Ковалёв"
    assert item.unread_messages_count == 1
    assert item.last_message_at is not None
    assert item.en_route_at is None
    assert item.my_review_rating is None

    provider_items, _ = await api.list_requests(world.dispatcher)
    provider_item = next(i for i in provider_items if i.id == scheduled["id"])
    assert provider_item.unread_messages_count == 0
    assert provider_item.last_message_at == item.last_message_at


async def test_list_item_hides_worker_until_assignment_accepted(world: World) -> None:
    submitted = await h.make_submitted(world)
    async with db_session.transaction() as session:
        await session.execute(
            update(Assignment)
            .where(Assignment.id == h.assignment_id(submitted))
            .values(field_worker_display_name="Андрей Ковалёв")
        )
    items, _ = await api.list_requests(world.manager)
    item = next(i for i in items if i.id == submitted["id"])
    assert item.field_worker_name is None


async def test_provider_list_counts_only_own_channel(world: World) -> None:
    rival = await factories.build_rival_provider(world)
    published = await h.make_published(world)
    request_id = h.rid(published)
    await api.post_dialog_message(world.dispatcher, request_id, body="Вопрос по доступу")
    offer = (
        await api.submit_offer(rival.dispatcher, request_id, data=api.OfferInput(amount_minor=1))
    ).body
    await api.select_offer(world.manager, request_id, offer_id=h.oid(offer))

    items, _ = await api.list_requests(rival.dispatcher)
    item = next(i for i in items if i.id == published["id"])
    assert item.unread_messages_count == 0
    assert item.last_message_at is None


async def test_list_item_review_rating_and_closed_at(world: World) -> None:
    from app.modules.reputation import api as reputation

    reported = await h.make_completion_reported(world)
    closed = await api.confirm_completion(
        world.manager,
        h.rid(reported),
        expected_version=reported["version"],
    )
    await reputation.submit_review(
        world.manager,
        h.rid(reported),
        reputation.ReviewSubmitData(rating=5, text="Хорошо"),
        idem=None,
    )
    items, _ = await api.list_requests(world.manager)
    item = next(i for i in items if i.id == reported["id"])
    assert item.my_review_rating == 5
    assert item.closed_at is not None
    assert closed.body["status"] == "closed"

    provider_items, _ = await api.list_requests(world.dispatcher)
    provider_item = next(i for i in provider_items if i.id == reported["id"])
    assert provider_item.my_review_rating is None


async def test_list_filters_by_equipment(world: World) -> None:
    first = await h.make_submitted(world)
    other = await api.create_draft(
        world.manager, equipment_id=world.other_equipment_id, symptom_description="Шумит"
    )

    items, _ = await api.list_requests(world.manager, equipment_id=world.equipment_id)
    assert [i.id for i in items] == [first["id"]]
    items, _ = await api.list_requests(world.manager, equipment_id=world.other_equipment_id)
    assert [i.id for i in items] == [other.body["id"]]


async def test_equipment_filter_respects_employee_locations(
    world: World, other_world: World
) -> None:
    await api.create_draft(
        world.manager, equipment_id=world.other_equipment_id, symptom_description="Шумит"
    )
    items, _ = await api.list_requests(world.employee, equipment_id=world.other_equipment_id)
    assert items == []
    items, _ = await api.list_requests(other_world.manager, equipment_id=world.other_equipment_id)
    assert items == []


async def test_assignment_carries_provider_rating_summary(world: World) -> None:
    submitted = await h.make_submitted(world)
    card = await _customer_card(world, submitted)
    assert card.assignment is not None and card.assignment.provider is not None
    provider = card.assignment.provider
    assert provider.display_name == "Холод-Сервис"
    assert provider.reviews_count == 0
    assert provider.rating is None
    assert provider.rating_label == get_settings().rating_no_reviews_label

    provider_view = await api.get_request(world.dispatcher, h.rid(submitted))
    assert isinstance(provider_view, RequestProviderView)
    assert provider_view.assignment.provider is None


async def test_offer_provider_has_reviews_count(world: World) -> None:
    published = await h.make_published(world)
    await api.submit_offer(
        world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1000)
    )
    offers = await api.list_offers(world.manager, h.rid(published))
    assert offers[0].provider is not None
    assert offers[0].provider.reviews_count == 0


async def test_names_before_and_after_assignment(world: World) -> None:
    published = await h.make_published(world)
    request_id = h.rid(published)
    await api.post_dialog_message(world.dispatcher, request_id, body="Какой этаж?")
    offer = (
        await api.submit_offer(world.dispatcher, request_id, data=api.OfferInput(amount_minor=1))
    ).body
    answer = await api.post_dialog_message(
        world.manager, request_id, body="Третий", offer_id=h.oid(offer)
    )
    assert answer.body["author_display_name"] == "Руководитель"

    thread, _ = await api.list_dialog_messages(world.manager, request_id, offer_id=h.oid(offer))
    question = thread[0]
    assert question.author_display_name is None
    assert question.author_organization_name == "Холод-Сервис"

    provider_thread, _ = await api.list_dialog_messages(world.dispatcher, request_id)
    customer_message = provider_thread[1]
    assert customer_message.author_display_name is None
    assert customer_message.author_organization_name is None
    assert provider_thread[0].author_display_name == "Диспетчер"

    selected = (await api.select_offer(world.manager, request_id, offer_id=h.oid(offer))).body
    accepted = (
        await api.accept_assignment(
            world.dispatcher,
            request_id,
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    await api.post_message(
        world.dispatcher, request_id, body="Выезжаю", assignment_id=h.assignment_id(accepted)
    )
    await api.post_message(world.manager, request_id, body="Ждём")

    messages, _ = await api.list_messages(world.manager, request_id)
    shared = [m for m in messages if m.thread_provider_id is None]
    assert shared[0].author_display_name == "Диспетчер"
    assert shared[0].author_organization_name == "Холод-Сервис"
    provider_messages, _ = await api.list_messages(world.dispatcher, request_id)
    shared = [m for m in provider_messages if m.thread_provider_id is None]
    assert shared[1].author_display_name == "Руководитель"
    assert shared[1].author_organization_name == "Сеть кафе"


async def test_crm_author_label(world: World) -> None:
    accepted = await h.make_accepted(world)
    request_id = h.rid(accepted)
    posted = await api.post_message(
        world.integration,
        request_id,
        body="Мастер будет в 14:30",
        assignment_id=h.assignment_id(accepted),
        author_label="  Ольга, диспетчер\u0007 ",
    )
    assert posted.body["author_label"] == "Ольга, диспетчер"
    messages, _ = await api.list_messages(world.manager, request_id)
    assert messages[-1].author_label == "Ольга, диспетчер"
    assert messages[-1].author_display_name == "CRM Холод-Сервис"
    assert messages[-1].author_organization_name == "Холод-Сервис"

    with pytest.raises(ValidationFailed):
        await api.post_message(
            world.dispatcher,
            request_id,
            body="Подпись",
            assignment_id=h.assignment_id(accepted),
            author_label="Директор",
        )
    with pytest.raises(ValidationFailed):
        await api.post_message(
            world.integration,
            request_id,
            body="Длинная подпись",
            assignment_id=h.assignment_id(accepted),
            author_label="x" * 101,
        )
    async with db_session.transaction() as session:
        payloads = list((await session.execute(select(RequestEvent.payload))).scalars())
    assert all("Ольга" not in str(payload) for payload in payloads)


async def test_customer_message_delivery_state(world: World) -> None:
    accepted = await h.make_accepted(world)
    request_id = h.rid(accepted)
    posted = await api.post_message(world.manager, request_id, body="Код домофона 12")
    assert posted.body["delivery"] is None

    events = await h.integration_events(request_id)
    event = next(e for e in events if e.event_type == "message.created")
    now = utcnow()
    async with db_session.transaction() as session:
        subscription = WebhookSubscription(
            integration_client_id=world.integration.integration_client_id,
            provider_org_id=world.provider_org_id,
            url="https://crm.example/hook",
            event_types=["message.created"],
            secret_encrypted=b"secret",
        )
        session.add(subscription)
        await session.flush()
        session.add(
            WebhookDelivery(
                integration_event_id=event.id,
                webhook_subscription_id=subscription.id,
                provider_org_id=world.provider_org_id,
                state="delivered",
                attempt_count=1,
                last_attempt_at=now,
                last_error="crm internal detail",
                expires_at=now + timedelta(days=1),
            )
        )

    messages, _ = await api.list_messages(world.manager, request_id)
    mine = next(m for m in messages if m.id == posted.body["id"])
    assert mine.delivery is not None and mine.delivery.state == "delivered"
    assert "crm internal detail" not in mine.model_dump_json()
    assert "crm.example" not in mine.model_dump_json()

    provider_messages, _ = await api.list_messages(world.dispatcher, request_id)
    assert all(m.delivery is None for m in provider_messages)


async def test_no_delivery_without_crm(world: World) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(IntegrationClient)
            .where(IntegrationClient.provider_org_id == world.provider_org_id)
            .values(status="revoked")
        )
    accepted = await h.make_accepted(world)
    posted = await api.post_message(world.manager, h.rid(accepted), body="Ждём")
    assert posted.body["delivery"] is None


async def test_public_card_has_city_and_district_names(world: World) -> None:
    published = await h.make_published(world)
    items, _ = await api.list_marketplace_requests(world.dispatcher)
    card = next(i for i in items if i.request_id == published["id"])
    async with db_session.transaction() as session:
        city = await session.get(City, world.city_id)
        district = await session.get(District, world.district_id)
    assert city is not None and district is not None
    assert card.city_name == city.name
    assert card.district_name == district.name
    dumped = card.model_dump_json()
    assert "Примерная" not in dumped
    assert "Кафе на Ленина" not in dumped

    detail = await api.get_marketplace_card(world.dispatcher, h.rid(published))
    assert detail.card.district_name == district.name


async def test_repair_quote_warranty_terms(world: World) -> None:
    accepted = await h.make_accepted(world)
    quoted = await api.create_repair_quote(
        world.dispatcher,
        h.rid(accepted),
        assignment_id=h.assignment_id(accepted),
        data=api.RepairQuoteInput(
            description_of_work="Замена компрессора",
            amount_minor=1500000,
            currency="RUB",
            warranty_terms="  3 месяца на работы  ",
        ),
        expected_version=accepted["version"],
    )
    assert quoted.body["repair_quotes"][0]["warranty_terms"] == "3 месяца на работы"
    card = await _customer_card(world, accepted)
    assert card.repair_quotes[0].warranty_terms == "3 месяца на работы"

    with pytest.raises(ValidationFailed):
        await api.create_repair_quote(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.RepairQuoteInput(
                description_of_work="Замена",
                amount_minor=100,
                currency="RUB",
                warranty_terms="x" * 1001,
            ),
            expected_version=quoted.body["version"],
        )


async def test_reminder_at_for_pending_own_service(world: World) -> None:
    submitted = await h.make_submitted(world)
    card = await _customer_card(world, submitted)
    assert card.assignment is not None and card.assignment.reminder_at is not None
    expected = card.assignment.created_at + timedelta(
        seconds=get_settings().own_service_reminder_seconds
    )
    assert card.assignment.reminder_at == expected

    accepted = await api.accept_assignment(
        world.dispatcher,
        h.rid(submitted),
        assignment_id=h.assignment_id(submitted),
        expected_version=submitted["version"],
    )
    assert accepted.body["assignment"]["reminder_at"] is None
    card = await _customer_card(world, submitted)
    assert card.assignment is not None and card.assignment.reminder_at is None


async def test_provider_membership_names_are_resolved(world: World) -> None:
    scheduled = await h.make_scheduled(world)
    async with db_session.transaction() as session:
        membership_id = (
            await session.execute(
                select(Membership.id).where(Membership.id == world.dispatcher.membership_id)
            )
        ).scalar_one()
    await api.set_field_worker(
        world.dispatcher,
        h.rid(scheduled),
        assignment_id=h.assignment_id(scheduled),
        membership_id=membership_id,
        expected_version=scheduled["version"],
    )
    items, _ = await api.list_requests(world.manager)
    item = next(i for i in items if i.id == scheduled["id"])
    assert item.field_worker_name == "Диспетчер"
    assert ids.decode("request", item.id) == h.rid(scheduled)
