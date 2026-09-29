from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Assignment, Offer, RepairRequest, ServiceBinding
from tests.db.factories import make_customer_chain, make_provider_org


async def _make_repair_request(session: AsyncSession) -> RepairRequest:
    customer_org, location, equipment, membership = await make_customer_chain(session)
    request = RepairRequest(
        customer_org_id=customer_org.id,
        location_id=location.id,
        equipment_id=equipment.id,
        author_membership_id=membership.id,
        route="own_service",
        status="searching",
        version=1,
        urgency="normal",
        equipment_snapshot={},
        location_snapshot={},
        disputed=False,
    )
    session.add(request)
    await session.flush()
    return request


async def test_one_active_assignment_per_request(db_session: AsyncSession) -> None:
    """ux_assignments_one_active_per_request: второе pending/accepted-назначение
    на ту же заявку запрещено."""
    request = await _make_repair_request(db_session)
    provider_a = await make_provider_org(db_session)
    provider_b = await make_provider_org(db_session)

    db_session.add(
        Assignment(
            request_id=request.id,
            provider_org_id=provider_a.id,
            route="own_service",
            state="pending",
            warranty_decision="not_stated",
        )
    )
    await db_session.flush()

    db_session.add(
        Assignment(
            request_id=request.id,
            provider_org_id=provider_b.id,
            route="own_service",
            state="pending",
            warranty_decision="not_stated",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_zero_price_offer_requires_reason(db_session: AsyncSession) -> None:
    """ck_offers_zero_cost: visit_amount_minor = 0 без zero_cost_reason запрещён."""
    request = await _make_repair_request(db_session)
    provider = await make_provider_org(db_session)

    db_session.add(
        Offer(
            request_id=request.id,
            provider_org_id=provider.id,
            version=1,
            visit_amount_minor=0,
            currency="RUB",
            valid_until=datetime.now(UTC) + timedelta(days=1),
            state="active",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_second_verified_provider_same_inn_rejected(db_session: AsyncSession) -> None:
    """ux_organizations_verified_provider_inn: второй verified-исполнитель
    с тем же ИНН запрещён (черновики с тем же ИНН допустимы, ТЗ 6.5.3)."""
    inn = "7700000000"
    org_a = await make_provider_org(db_session, inn_normalized=inn)
    org_a.details_verification_status = "verified"
    org_a.representative_verification_status = "verified"
    await db_session.flush()

    org_b = await make_provider_org(db_session, inn_normalized=inn)
    org_b.details_verification_status = "verified"
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_service_binding_requires_provider_or_contact(db_session: AsyncSession) -> None:
    """ck_service_bindings_provider_or_contact: ровно один из provider_org_id/
    personal_contact_name — без исполнителя и без личного контакта запрещено."""
    customer_org, _location, equipment, membership = await make_customer_chain(db_session)

    db_session.add(
        ServiceBinding(
            equipment_id=equipment.id,
            customer_org_id=customer_org.id,
            basis="preferred_provider",
            status="pending",
            created_by_membership_id=membership.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
