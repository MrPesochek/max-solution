from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import ValidationFailed
from app.db import session as db_session
from app.modules.requests import api, queries, support
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


@contextmanager
def _counting(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def _accepted_with_messages(world: World) -> dict[str, Any]:
    accepted = await h.make_accepted(world)
    await api.post_message(
        world.dispatcher,
        h.rid(accepted),
        body="Выезжаю",
        assignment_id=h.assignment_id(accepted),
    )
    await api.post_message(world.employee, h.rid(accepted), body="Ждём")
    return accepted


async def _queries_for(engine: AsyncEngine, actor: Any) -> tuple[int, int]:
    with _counting(engine) as statements:
        items, _ = await api.list_requests(actor, limit=50)
    return len(items), len(statements)


async def test_query_count_does_not_grow_with_rows(world: World, db_engine: AsyncEngine) -> None:
    await _accepted_with_messages(world)
    one = {
        name: await _queries_for(db_engine, actor)
        for name, actor in (
            ("manager", world.manager),
            ("dispatcher", world.dispatcher),
            ("integration", world.integration),
        )
    }

    for _ in range(4):
        await _accepted_with_messages(world)
    await h.make_submitted(world)

    for name, actor in (
        ("manager", world.manager),
        ("dispatcher", world.dispatcher),
        ("integration", world.integration),
    ):
        rows, count = await _queries_for(db_engine, actor)
        assert rows == 6, name
        assert one[name][0] == 1, name
        assert count == one[name][1], name


async def test_batched_counters_match_card_counters(world: World) -> None:
    """Регресс: пакетные счётчики совпадают с теми, что карточка считает по одной заявке."""
    first = await _accepted_with_messages(world)
    second = await _accepted_with_messages(world)
    await api.mark_messages_read(world.manager, h.rid(first))
    await api.post_message(
        world.dispatcher, h.rid(first), body="Ещё", assignment_id=h.assignment_id(first)
    )
    silent = await h.make_submitted(world)

    for actor in (world.manager, world.dispatcher):
        items, _ = await api.list_requests(actor, limit=50)
        by_id = {item.id: item for item in items}
        async with db_session.get_sessionmaker()() as session:
            for body in (first, second, silent):
                request_id = h.rid(body)
                channel = queries.WHOLE_CHANNEL
                if actor is world.dispatcher:
                    assignment = await queries.get_assignment(session, h.assignment_id(body))
                    assert assignment is not None
                    channel = support.provider_channel(assignment)
                expected = await support.unread_for(session, actor, request_id, channel=channel)
                assert by_id[body["id"]].unread_messages_count == expected

    manager_items = {i.id: i for i in (await api.list_requests(world.manager))[0]}
    assert manager_items[first["id"]].unread_messages_count == 1
    assert manager_items[second["id"]].unread_messages_count == 2
    assert manager_items[silent["id"]].unread_messages_count == 0
    assert manager_items[silent["id"]].last_message_at is None
    assert manager_items[first["id"]].last_message_at is not None

    crm_items = {i.id: i for i in (await api.list_requests(world.integration))[0]}
    assert crm_items[first["id"]].unread_messages_count is None
    assert crm_items[first["id"]].last_message_at == manager_items[first["id"]].last_message_at


async def test_own_messages_are_not_unread(world: World) -> None:
    """Запрет: собственные сообщения читателя в непрочитанное не попадают."""
    accepted = await _accepted_with_messages(world)
    items, _ = await api.list_requests(world.dispatcher)
    [item] = [i for i in items if i.id == accepted["id"]]
    assert item.unread_messages_count == 1


async def test_provider_queues_are_filtered_on_server(world: World) -> None:
    """«Входящие» и «В работе» — серверным фильтром, а не на клиенте после limit."""
    pending = await h.make_submitted(world)
    accepted = await h.make_accepted(world)

    incoming, _ = await api.list_requests(world.dispatcher, assignment_states=["pending"])
    in_work, _ = await api.list_requests(world.dispatcher, assignment_states=["accepted"])
    both, _ = await api.list_requests(world.dispatcher, assignment_states=["pending", "accepted"])
    assert [i.id for i in incoming] == [pending["id"]]
    assert [i.id for i in in_work] == [accepted["id"]]
    assert {i.id for i in both} == {pending["id"], accepted["id"]}

    with pytest.raises(ValidationFailed):
        await api.list_requests(world.dispatcher, assignment_states=["declined"])
