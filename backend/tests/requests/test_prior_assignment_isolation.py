from typing import Any

import pytest

from app.core import ids
from app.db import session as db_session
from app.db.models import Message, ServiceBinding
from app.modules.requests import api
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")

SECRET_REASON = "Причина для прежнего сервиса"
INTERCOM = "Код домофона 1234"
FORMER_PHONE = "Мастер Иван +79990000000"


async def _former_assignment(world: World) -> dict[str, Any]:
    accepted = await h.make_marketplace_accepted(world)
    request_id = h.rid(accepted)
    await api.post_message(world.manager, request_id, body=INTERCOM)
    await api.post_message(
        world.dispatcher, request_id, body=FORMER_PHONE, assignment_id=h.assignment_id(accepted)
    )
    await h.change_provider_and_republish(world, accepted, reason=SECRET_REASON)
    return accepted


async def _second_provider_selected(world: World) -> tuple[World, dict[str, Any]]:
    rival = await factories.build_rival_provider(world)
    former = await _former_assignment(world)
    return rival, await h.select_next_provider(world, rival, h.rid(former))


async def test_new_provider_does_not_see_former_cancellation(world: World) -> None:
    rival, selected = await _second_provider_selected(world)

    card = await api.get_request(rival.dispatcher, h.rid(selected))
    assert card.cancellation is None
    confirmed = (
        await api.accept_assignment(
            rival.dispatcher,
            h.rid(selected),
            assignment_id=h.assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    assert confirmed["cancellation"] is None

    customer_card = await api.get_request(world.manager, h.rid(selected))
    assert customer_card.cancellation is None


async def test_customer_sees_former_cancellation_until_new_assignment(world: World) -> None:
    former = await _former_assignment(world)

    customer_card = await api.get_request(world.manager, h.rid(former))
    assert customer_card.cancellation is not None
    assert customer_card.cancellation.reason == SECRET_REASON
    assert customer_card.cancellation.status == "accepted"


async def test_new_provider_channel_excludes_former_messages(world: World) -> None:
    rival, selected = await _second_provider_selected(world)
    request_id = h.rid(selected)

    messages, _ = await api.list_messages(rival.dispatcher, request_id)
    assert messages == []
    card = await api.get_request(rival.dispatcher, request_id)
    assert card.unread_messages_count == 0
    read = (await api.mark_messages_read(rival.dispatcher, request_id)).body
    assert read["last_read_message_id"] is None
    assert read["unread_messages_count"] == 0

    await api.post_message(world.manager, request_id, body="Для нового сервиса")
    messages, _ = await api.list_messages(rival.dispatcher, request_id)
    assert [m.body for m in messages] == ["Для нового сервиса"]

    customer_messages, _ = await api.list_messages(world.manager, request_id)
    assert [m.body for m in customer_messages] == [INTERCOM, FORMER_PHONE, "Для нового сервиса"]


async def test_reassigned_same_provider_sees_only_current_assignment(world: World) -> None:
    former = await _former_assignment(world)
    selected = await h.select_next_provider(world, world, h.rid(former), amount_minor=1500)
    assert h.assignment_id(selected) != h.assignment_id(former)

    messages, _ = await api.list_messages(world.dispatcher, h.rid(former))
    assert messages == []
    card = await api.get_request(world.dispatcher, h.rid(former))
    assert card.cancellation is None


async def test_messages_store_assignment_of_shared_channel(world: World) -> None:
    accepted = await h.make_marketplace_accepted(world)
    message = (await api.post_message(world.manager, h.rid(accepted), body="Жду мастера")).body
    async with db_session.transaction() as session:
        row = await session.get(Message, ids.decode("message", message["id"]))
        assert row is not None
        assert row.assignment_id == h.assignment_id(accepted)


async def test_provider_list_hides_customer_until_disclosure(world: World) -> None:
    async with db_session.transaction() as session:
        binding = await session.get(ServiceBinding, world.binding_id)
        assert binding is not None
        binding.claimed_contract_number = "Д-17"
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body

    items, _ = await api.list_requests(world.dispatcher)
    (item,) = [i for i in items if i.id == selected["id"]]
    assert (item.location_name, item.customer_org_name, item.contract_number) == (None, None, None)

    await api.accept_assignment(
        world.dispatcher,
        h.rid(selected),
        assignment_id=h.assignment_id(selected),
        expected_version=selected["version"],
    )
    items, _ = await api.list_requests(world.dispatcher)
    (item,) = [i for i in items if i.id == selected["id"]]
    assert item.location_name is not None
    assert item.customer_org_name is not None
    assert item.contract_number == "Д-17"


async def test_own_service_list_discloses_before_acceptance(world: World) -> None:
    submitted = await h.make_submitted(world)
    items, _ = await api.list_requests(world.dispatcher)
    (item,) = [i for i in items if i.id == submitted["id"]]
    assert item.location_name is not None
    assert item.customer_org_name is not None


async def test_provider_history_names_customer_only_after_disclosure(world: World) -> None:
    published = await h.make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, h.rid(published), data=api.OfferInput(amount_minor=1000)
        )
    ).body
    selected = (await api.select_offer(world.manager, h.rid(published), offer_id=h.oid(offer))).body

    events, _ = await api.request_history(world.dispatcher, h.rid(selected))
    (chosen,) = [e for e in events if e.event_type == "OfferSelected"]
    assert chosen.actor_display_name is None

    await api.accept_assignment(
        world.dispatcher,
        h.rid(selected),
        assignment_id=h.assignment_id(selected),
        expected_version=selected["version"],
    )
    events, _ = await api.request_history(world.dispatcher, h.rid(selected))
    (chosen,) = [e for e in events if e.event_type == "OfferSelected"]
    assert chosen.actor_display_name == "Сеть кафе"
