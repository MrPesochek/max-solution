from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Assignment,
    AuditEntry,
    IdempotencyKey,
    IntegrationClient,
    IntegrationEvent,
    Membership,
    Notification,
    Organization,
    RepairRequest,
    User,
)
from tests.db.factories import make_customer_chain, make_provider_org


async def test_user_defaults(db_session: AsyncSession) -> None:
    user = User(max_user_id="max-smoke-user", display_name="Смок Тестов")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.bot_available is False
    assert user.bot_started_at is None
    assert user.created_at is not None
    assert user.updated_at is not None


async def test_organization_defaults(db_session: AsyncSession) -> None:
    org = Organization(is_customer=True, legal_name="ООО Смок", display_name="Смок")
    db_session.add(org)
    await db_session.flush()
    await db_session.refresh(org)

    assert org.is_provider is False
    assert org.details_verification_status == "unverified"
    assert org.representative_verification_status == "unverified"


async def test_membership_defaults(db_session: AsyncSession) -> None:
    org = Organization(is_customer=True, legal_name="ООО Смок", display_name="Смок")
    db_session.add(org)
    user = User(max_user_id="max-smoke-membership", display_name="Смок Тестов")
    db_session.add(user)
    await db_session.flush()

    membership = Membership(user_id=user.id, organization_id=org.id, role="customer_employee")
    db_session.add(membership)
    await db_session.flush()
    await db_session.refresh(membership)

    assert membership.status == "pending"


async def test_repair_request_defaults(db_session: AsyncSession) -> None:
    customer_org, location, equipment, membership = await make_customer_chain(db_session)

    request = RepairRequest(
        customer_org_id=customer_org.id,
        location_id=location.id,
        equipment_id=equipment.id,
        author_membership_id=membership.id,
        route="own_service",
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)

    assert request.request_number is not None
    assert request.status == "draft"
    assert request.version == 1
    assert request.urgency == "normal"
    assert request.equipment_snapshot == {}
    assert request.location_snapshot == {}
    assert request.disputed is False


async def test_assignment_defaults(db_session: AsyncSession) -> None:
    customer_org, location, equipment, membership = await make_customer_chain(db_session)
    request = RepairRequest(
        customer_org_id=customer_org.id,
        location_id=location.id,
        equipment_id=equipment.id,
        author_membership_id=membership.id,
        route="own_service",
    )
    db_session.add(request)
    await db_session.flush()
    provider = await make_provider_org(db_session)

    assignment = Assignment(request_id=request.id, provider_org_id=provider.id, route="own_service")
    db_session.add(assignment)
    await db_session.flush()
    await db_session.refresh(assignment)

    assert assignment.state == "pending"
    assert assignment.warranty_decision == "not_stated"


async def test_notification_defaults(db_session: AsyncSession) -> None:
    user = User(max_user_id="max-smoke-notification", display_name="Смок Тестов")
    db_session.add(user)
    await db_session.flush()

    notification = Notification(recipient_user_id=user.id, notification_type="request.changed")
    db_session.add(notification)
    await db_session.flush()
    await db_session.refresh(notification)

    assert notification.payload == {}
    assert notification.state == "queued"
    assert notification.attempt_count == 0


async def test_integration_event_defaults(db_session: AsyncSession) -> None:
    customer_org, *_ = await make_customer_chain(db_session)

    event = IntegrationEvent(
        event_type="request.changed",
        recipient_org_id=customer_org.id,
        resource_kind="repair_request",
        resource_id=customer_org.id,
        payload={},
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.refresh(event)

    assert event.occurred_at is not None


async def test_idempotency_key_defaults(db_session: AsyncSession) -> None:
    key = IdempotencyKey(
        scope="requests.create",
        key="smoke-key",
        request_path="/requests",
        request_body_hash=b"\x00" * 32,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(key)
    await db_session.flush()
    await db_session.refresh(key)

    assert key.created_at is not None


async def test_audit_entry_defaults(db_session: AsyncSession) -> None:
    entry = AuditEntry(
        actor_kind="system", object_type="repair_request", action="create", result="success"
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.refresh(entry)

    assert entry.details == {}
    assert entry.occurred_at is not None


async def test_integration_client_defaults(db_session: AsyncSession) -> None:
    provider = await make_provider_org(db_session)
    client = IntegrationClient(
        provider_org_id=provider.id,
        name="Смок-интеграция",
        api_key_hash=b"\x01" * 32,
        api_key_prefix="smk_",
    )
    db_session.add(client)
    await db_session.flush()
    await db_session.refresh(client)

    assert client.scopes == []
    assert client.status == "active"
