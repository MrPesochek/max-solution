import pytest

from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")

_SENSITIVE = ("ул. Примерная", "+70000000000", "SN-0001")


async def test_submit_creates_event_and_notifications(world: World) -> None:
    submitted = await h.make_submitted(world)
    events = await h.integration_events()
    assert [event.event_type for event in events] == ["request.assigned"]
    event = events[0]
    assert event.recipient_org_id == world.provider_org_id
    assert event.resource_kind == "request"
    assert event.resource_version == submitted["version"]
    assert event.payload["request"]["status"] == "awaiting_provider"
    assert event.payload["request"]["contacts_disclosed"] is True

    notified = await h.notifications()
    kinds = sorted(n.notification_type for n in notified)
    assert kinds == [
        "request.assigned",
        "request.assigned",
        "request.submitted",
        "request.submitted",
    ]
    for notification in notified:
        payload = str(notification.payload)
        assert all(secret not in payload for secret in _SENSITIVE)
        assert notification.request_id is not None


async def test_approvals_notify_only_managers(world: World) -> None:
    accepted = await h.make_accepted(world)
    before = len(await h.notifications())
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            h.rid(accepted),
            assignment_id=h.assignment_id(accepted),
            data=api.VisitProposalInput(**h.visit_window(), amount_minor=150000, currency="RUB"),
            expected_version=accepted["version"],
        )
    ).body
    fresh = (await h.notifications())[before:]
    assert [n.notification_type for n in fresh] == ["visit_proposal.created"]
    assert fresh[0].recipient_membership_id == world.manager.membership_id

    events = await h.integration_events()
    changed = [e for e in events if e.event_type == "request.changed"]
    assert changed[-1].payload["change_kind"] == "visit_proposed"
    assert changed[-1].payload["visit_proposal"]["version"] == 1

    before = len(await h.notifications())
    await api.approve_visit_proposal(
        world.manager,
        h.rid(proposed),
        proposal_id=h.proposal_id(proposed),
        proposal_version=1,
        expected_version=proposed["version"],
    )
    responded = [
        e for e in await h.integration_events() if e.event_type == "visit_proposal.responded"
    ]
    assert len(responded) == 1
    assert responded[0].payload["visit_proposal"]["status"] == "approved"
    fresh = (await h.notifications())[before:]
    assert [n.notification_type for n in fresh] == [
        "visit_proposal.approved",
        "visit_proposal.approved",
    ]


async def test_closing_emits_request_closed(world: World) -> None:
    reported = await h.make_completion_reported(world)
    await api.confirm_completion(
        world.manager, h.rid(reported), expected_version=reported["version"]
    )
    types = await h.event_types()
    assert types == [
        "request.assigned",
        "request.changed",
        "visit_proposal.responded",
        "request.changed",
        "request.changed",
        "request.closed",
    ]
    closed = (await h.integration_events())[-1]
    assert closed.payload["request"]["assignment"]["state"] == "completed"


async def test_message_event_contains_message_only(world: World) -> None:
    accepted = await h.make_accepted(world)
    await api.post_message(world.employee, h.rid(accepted), body="Приедете сегодня?")
    message_events = [e for e in await h.integration_events() if e.event_type == "message.created"]
    assert len(message_events) == 1
    assert message_events[0].payload["message"]["body"] == "Приедете сегодня?"


async def test_declined_provider_gets_reason_but_customer_keeps_request(world: World) -> None:
    submitted = await h.make_submitted(world)
    await api.decline_assignment(
        world.dispatcher,
        h.rid(submitted),
        assignment_id=h.assignment_id(submitted),
        reason="Нет мастера",
        expected_version=submitted["version"],
    )
    events = await h.integration_events()
    assert events[-1].event_type == "request.changed"
    assert events[-1].payload["change_kind"] == "provider_declined"
    assert events[-1].payload["request"]["contacts_disclosed"] is False
    assert events[-1].payload["request"]["location"]["address"] is None

    names = [n.notification_type for n in await h.notifications()]
    assert names.count("request.declined") == 1
