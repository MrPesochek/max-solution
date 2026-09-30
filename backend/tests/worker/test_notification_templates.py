from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.modules.requests import api
from app.modules.requests.commands import VisitProposalInput
from app.worker import notification_templates as templates
from tests.requests import factories as req_factories
from tests.requests import helpers as req_helpers
from tests.requests.helpers import assignment_id, rid

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return utcnow()


async def test_known_types_are_registered() -> None:
    types = templates.registered_types()
    assert {
        "request.assigned",
        "request.submitted",
        "request.accepted",
        "integration.api_key.created",
        "visit_proposal.created",
        "repair_quote.created",
        "completion.reported",
        "message.created",
        "cancellation.requested",
    } <= types


async def test_unknown_type_gets_safe_text_and_button(db_session: AsyncSession) -> None:
    message = await templates.render(
        db_session,
        "никто.такого.не.шлёт",
        {"secret": "не должно попасть в текст"},
        recipient_user_id=(await req_factories.create_user(db_session)).id,
        now=_now(),
    )
    assert message.text == templates.FALLBACK_TEXT
    assert message.attachments


async def test_api_key_template_uses_payload_name(db_session: AsyncSession) -> None:
    user = await req_factories.create_user(db_session)
    message = await templates.render(
        db_session,
        "integration.api_key.created",
        {"name": "CRM"},
        recipient_user_id=user.id,
        now=_now(),
    )
    assert message.text == "Выпущен ключ интеграции «CRM»"


async def test_api_key_template_without_name(db_session: AsyncSession) -> None:
    user = await req_factories.create_user(db_session)
    message = await templates.render(
        db_session, "integration.api_key.created", {}, recipient_user_id=user.id, now=_now()
    )
    assert message.text == "Выпущен ключ интеграции"


async def test_visit_proposal_current_state_has_approve_reject(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    accepted = await req_helpers.make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            rid(accepted),
            assignment_id=assignment_id(accepted),
            data=VisitProposalInput(
                **req_helpers.visit_window(),
                amount_minor=15000,
                currency="RUB",
                scope_description="Замена термостата",
            ),
            expected_version=accepted["version"],
        )
    ).body

    payload = {
        "request_id": proposed["id"],
        "visit_proposal_id": proposed["visit_proposals"][0]["id"],
        "proposal_version": proposed["visit_proposals"][0]["version"],
    }
    message = await templates.render(
        db_session,
        "visit_proposal.created",
        payload,
        recipient_user_id=world.manager.user_id,
        now=_now(),
    )
    assert "версия 1" in message.text
    assert "15000" not in message.text
    assert message.attachments
    buttons = [b for row in message.attachments[0].payload.buttons for b in row]
    assert {b.text for b in buttons} == {"Согласовать выезд (версия 1)", "Отклонить выезд"}


async def test_visit_proposal_outdated_state_has_no_buttons(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    accepted = await req_helpers.make_accepted(world)
    first = (
        await api.propose_visit(
            world.dispatcher,
            rid(accepted),
            assignment_id=assignment_id(accepted),
            data=VisitProposalInput(
                **req_helpers.visit_window(),
                amount_minor=15000,
                currency="RUB",
                scope_description="Осмотр",
            ),
            expected_version=accepted["version"],
        )
    ).body
    await api.propose_visit(
        world.dispatcher,
        rid(accepted),
        assignment_id=assignment_id(accepted),
        data=VisitProposalInput(
            **req_helpers.visit_window(),
            amount_minor=20000,
            currency="RUB",
            scope_description="Осмотр и чистка",
        ),
        expected_version=first["version"],
    )

    stale_payload = {
        "request_id": first["id"],
        "visit_proposal_id": first["visit_proposals"][0]["id"],
        "proposal_version": first["visit_proposals"][0]["version"],
    }
    message = await templates.render(
        db_session,
        "visit_proposal.created",
        stale_payload,
        recipient_user_id=world.manager.user_id,
        now=_now(),
    )
    assert "неактуальны" in message.text
    assert message.attachments
    buttons = [b for row in message.attachments[0].payload.buttons for b in row]
    assert {b.text for b in buttons} == {"Открыть"}


async def test_request_assigned_has_accept_decline_when_pending(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    submitted = await req_helpers.make_submitted(world)
    payload = {"request_id": submitted["id"], "assignment_id": submitted["assignment"]["id"]}

    message = await templates.render(
        db_session,
        "request.assigned",
        payload,
        recipient_user_id=world.dispatcher.user_id,
        now=_now(),
    )
    buttons = [b for row in message.attachments[0].payload.buttons for b in row]
    assert {b.text for b in buttons} == {"Принять", "Отклонить"}


async def test_request_assigned_outdated_after_accept(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    submitted = await req_helpers.make_submitted(world)
    payload = {"request_id": submitted["id"], "assignment_id": submitted["assignment"]["id"]}
    await api.accept_assignment(
        world.dispatcher,
        rid(submitted),
        assignment_id=assignment_id(submitted),
        expected_version=submitted["version"],
    )

    message = await templates.render(
        db_session,
        "request.assigned",
        payload,
        recipient_user_id=world.dispatcher.user_id,
        now=_now(),
    )
    assert "неактуальны" in message.text


async def test_completion_reported_has_confirm_when_actual(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    reported = await req_helpers.make_completion_reported(world)
    payload = {"request_id": reported["id"], "outcome": "resolved"}

    message = await templates.render(
        db_session,
        "completion.reported",
        payload,
        recipient_user_id=world.manager.user_id,
        now=_now(),
    )
    buttons = [b for row in message.attachments[0].payload.buttons for b in row]
    assert {b.text for b in buttons} == {"Подтвердить", "Проблема осталась"}


async def test_completion_reported_outdated_after_confirm(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    reported = await req_helpers.make_completion_reported(world)
    payload = {"request_id": reported["id"], "outcome": "resolved"}
    await api.confirm_completion(world.manager, rid(reported), expected_version=reported["version"])

    message = await templates.render(
        db_session,
        "completion.reported",
        payload,
        recipient_user_id=world.manager.user_id,
        now=_now(),
    )
    assert "неактуальны" in message.text


async def test_cancellation_notice_renders_its_own_cancellation(
    clean_db: None, db_session: AsyncSession
) -> None:
    world = await req_factories.build_world()
    rival = await req_factories.build_rival_provider(world)
    accepted = await req_helpers.make_marketplace_accepted(world)
    await req_helpers.change_provider_and_republish(world, accepted, reason="Для прежнего")
    (former_notice,) = [
        n
        for n in await req_helpers.notifications()
        if n.notification_type == "cancellation.requested"
        and n.recipient_user_id == world.dispatcher.user_id
    ]
    assert former_notice.payload["cancellation_id"]

    selected = await req_helpers.select_next_provider(world, rival, rid(accepted))
    confirmed = (
        await api.accept_assignment(
            rival.dispatcher,
            rid(accepted),
            assignment_id=assignment_id(selected),
            expected_version=selected["version"],
        )
    ).body
    await api.request_cancellation(
        world.manager,
        rid(accepted),
        target="cancel_request",
        reason="Секрет для нового сервиса",
        expected_version=confirmed["version"],
    )

    message = await templates.render(
        db_session,
        "cancellation.requested",
        former_notice.payload,
        recipient_user_id=world.dispatcher.user_id,
        now=_now(),
    )
    assert "Секрет" not in message.text
    assert templates.NOW_OUTDATED in message.text
