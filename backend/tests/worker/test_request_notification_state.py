from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.models import Notification
from app.modules.identity import api as identity
from app.modules.requests import api
from app.modules.requests.commands import VisitProposalInput
from app.worker import notification_dispatcher
from app.worker import notification_templates as templates
from tests.requests import factories as req_factories
from tests.requests import helpers as h

pytestmark = pytest.mark.asyncio


async def _last(notification_type: str) -> Notification:
    rows = [n for n in await h.notifications() if n.notification_type == notification_type]
    assert rows, notification_type
    return rows[-1]


async def _render(session: AsyncSession, row: Notification) -> templates.OutgoingMessage:
    return await templates.render(
        session,
        row.notification_type,
        dict(row.payload),
        recipient_user_id=row.recipient_user_id,
        recipient_membership_id=row.recipient_membership_id,
        now=utcnow(),
    )


async def _repropose(world: req_factories.World, body: dict[str, Any]) -> dict[str, Any]:
    return (
        await api.propose_visit(
            world.dispatcher,
            h.rid(body),
            assignment_id=h.assignment_id(body),
            data=VisitProposalInput(amount_minor=1000, currency="RUB", **h.visit_window()),
            expected_version=body["version"],
        )
    ).body


async def test_en_route_is_skipped_after_mark_is_reset(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    scheduled = await h.make_scheduled(world)
    marked = (
        await api.mark_en_route(
            world.dispatcher,
            h.rid(scheduled),
            assignment_id=h.assignment_id(scheduled),
            expected_version=scheduled["version"],
        )
    ).body
    row = await _last("field_worker.en_route")
    fresh = await _render(db_session, row)
    assert fresh.skip_reason is None
    assert "Мастер выехал" in fresh.text
    assert fresh.text.startswith(f"№{scheduled['request_number']}")

    await _repropose(world, marked)
    stale = await _render(db_session, row)
    assert stale.skip_reason == "en_route_outdated"

    job = notification_dispatcher.NotificationJob(
        notification_id=row.id,
        notification_type=row.notification_type,
        payload=dict(row.payload),
        max_user_id="100",
        recipient_user_id=row.recipient_user_id,
        attempt=1,
        recipient_membership_id=row.recipient_membership_id,
    )

    class _Transport:
        sent = 0

        async def send_message(self, **_: Any) -> None:
            self.sent += 1

    transport = _Transport()
    await notification_dispatcher._send(job, transport)  # type: ignore[arg-type]
    assert transport.sent == 0
    async with db_session_module_transaction() as session:
        stored = await session.get(Notification, row.id)
        assert stored is not None and stored.state == "skipped"
        assert stored.last_error == "en_route_outdated"


def db_session_module_transaction() -> Any:
    return db_session.transaction()


async def test_returned_to_draft_carries_manager_comment(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    draft = (
        await api.create_draft(world.employee, equipment_id=world.equipment_id, route="marketplace")
    ).body
    sent = (
        await api.request_approval(world.employee, h.rid(draft), expected_version=draft["version"])
    ).body
    await api.return_to_draft(
        world.manager,
        h.rid(draft),
        comment="Добавьте фото шильдика",
        expected_version=sent["version"],
    )
    message = await _render(db_session, await _last("request.returned_to_draft"))
    assert "Добавьте фото шильдика" in message.text
    assert f"№{draft['request_number']}" in message.text


async def test_simple_request_notification_names_the_request(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    accepted = await h.make_accepted(world)
    message = await _render(db_session, await _last("request.accepted"))
    assert message.text.startswith(f"№{accepted['request_number']}")
    assert "Исполнитель принял заявку" in message.text


async def test_own_service_no_answer_offers_contact_and_is_skipped_after_answer(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    submitted = await h.make_submitted(world)
    user = await req_factories.create_user(db_session)
    await db_session.commit()
    payload = {"request_id": ids.encode("request", h.rid(submitted))}
    message = await templates.render(
        db_session, "own_service.no_answer", payload, recipient_user_id=user.id, now=utcnow()
    )
    assert "Холод-Сервис" in message.text
    assert message.skip_reason is None

    await api.accept_assignment(
        world.dispatcher, h.rid(submitted), assignment_id=h.assignment_id(submitted)
    )
    async with db_session_module_transaction() as fresh:
        outdated = await templates.render(
            fresh, "own_service.no_answer", payload, recipient_user_id=user.id, now=utcnow()
        )
    assert outdated.skip_reason == "own_service_answered"


async def test_access_request_shows_who_where_and_note(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    await identity.request_access(
        world.employee,
        identity.AccessRequestData(
            location_id=ids.encode("location", world.other_location_id),
            note="Перевели на вторую точку",
        ),
        idem=None,
    )
    row = await _last("membership.access_requested")
    assert row.payload["note"] == "Перевели на вторую точку"
    message = await _render(db_session, row)
    assert "Перевели на вторую точку" in message.text
    assert "Точка:" in message.text
    assert "просит открыть доступ" in message.text
