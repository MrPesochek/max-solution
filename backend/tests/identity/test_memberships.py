import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Membership
from app.modules.identity import api as identity
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="membership", body_hash=hash_body({"k": key}))


def _actor(
    membership: Membership, *, location_ids: frozenset[uuid.UUID] | None = None
) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
        location_ids=location_ids,
    )


def _session_info(user_id: uuid.UUID) -> identity.SessionInfo:
    return identity.SessionInfo(
        session_id=uuid.uuid4(),
        user_id=user_id,
        display_name="Тест",
        expires_at=utcnow() + timedelta(hours=1),
    )


async def test_list_members_shows_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m1"), org
        )
        await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="e1"),
            org,
            role="customer_employee",
            locations=[location],
        )
        actor = _actor(manager)
        location_public_id = ids.encode("location", location.id)

    items, cursor = await identity.list_members(scope_of(actor))
    assert cursor is None
    employees = [m for m in items if m.role == "customer_employee"]
    assert employees[0].location_ids == [location_public_id]


async def test_members_of_other_organization_are_invisible() -> None:
    async with db_session.transaction() as s:
        mine = await factories.create_organization(s, name="Моя")
        other = await factories.create_organization(s, name="Чужая")
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m2"), mine
        )
        stranger = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="s2"), other
        )
        actor = _actor(manager)
        stranger_id = ids.encode("membership", stranger.id)

    items, _ = await identity.list_members(scope_of(actor))
    assert [m.id for m in items] == [ids.encode("membership", manager.id)]

    with pytest.raises(NotFound):
        await identity.revoke_membership(actor, stranger_id, idem=_idem("rev-1"))


async def test_cannot_revoke_last_manager() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m3"), org
        )
        actor = _actor(manager)
        own_id = ids.encode("membership", manager.id)

    with pytest.raises(Conflict) as exc:
        await identity.revoke_membership(actor, own_id, idem=_idem("rev-2"))
    assert exc.value.code == "LAST_MANAGER"


async def test_revoke_blocks_next_request() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m4"), org
        )
        employee_user = await factories.create_user(s, max_user_id="e4")
        employee = await factories.create_membership(
            s, employee_user, org, role="customer_employee"
        )
        actor = _actor(manager)
        employee_public_id = ids.encode("membership", employee.id)
        org_public_id = ids.encode("organization", org.id)
        employee_user_id = employee_user.id

    info = _session_info(employee_user_id)
    resolved = await identity.resolve_actor(info, org_public_id)
    assert isinstance(resolved, UserActor)

    await identity.revoke_membership(actor, employee_public_id, idem=_idem("rev-3"))

    with pytest.raises(NotFound):
        await identity.resolve_actor(info, org_public_id)


async def test_employee_cannot_manage_members() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        employee = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="e5"),
            org,
            role="customer_employee",
        )
        actor = _actor(employee, location_ids=frozenset())
        own_id = ids.encode("membership", employee.id)

    with pytest.raises(Forbidden):
        await identity.revoke_membership(actor, own_id, idem=_idem("rev-4"))
    with pytest.raises(Forbidden):
        await identity.set_membership_locations(actor, own_id, [], idem=_idem("loc-1"))


async def test_set_membership_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        other = await factories.create_organization(s, name="Чужая")
        mine = await factories.create_location(s, org, name="Своя точка")
        foreign = await factories.create_location(s, other, name="Чужая точка")
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m6"), org
        )
        employee = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="e6"), org, role="customer_employee"
        )
        actor = _actor(manager)
        employee_id = ids.encode("membership", employee.id)
        mine_id = ids.encode("location", mine.id)
        foreign_id = ids.encode("location", foreign.id)

    result = await identity.set_membership_locations(
        actor, employee_id, [mine_id], idem=_idem("loc-2")
    )
    assert result.body["location_ids"] == [mine_id]

    with pytest.raises(NotFound):
        await identity.set_membership_locations(
            actor, employee_id, [foreign_id], idem=_idem("loc-3")
        )


async def test_provider_admin_approves_pending_membership() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, customer=False, provider=True)
        admin = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="pa1"), org, role="provider_admin"
        )
        pending = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="pd1"),
            org,
            role="provider_dispatcher",
            status="pending",
        )
        actor = _actor(admin)
        pending_id = ids.encode("membership", pending.id)

    result = await identity.approve_membership(actor, pending_id, idem=_idem("appr-1"))
    assert result.body["status"] == "active"

    with pytest.raises(Conflict):
        await identity.approve_membership(actor, pending_id, idem=_idem("appr-2"))

    async with db_session.transaction() as s:
        stmt = select(Membership).where(Membership.id == ids.decode("membership", pending_id))
        row = (await s.execute(stmt)).scalar_one()
    assert row.status == "active"


async def test_manager_cannot_revoke_self_even_with_other_manager() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m7"), org
        )
        second = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m8"), org
        )
        actor = _actor(manager)
        own_id = ids.encode("membership", manager.id)
        second_id = ids.encode("membership", second.id)

    with pytest.raises(Conflict) as exc:
        await identity.revoke_membership(actor, own_id, idem=_idem("rev-self"))
    assert exc.value.code == "SELF_REVOKE"

    result = await identity.revoke_membership(actor, second_id, idem=_idem("rev-second"))
    assert result.body["status"] == "revoked"

    with pytest.raises(Conflict) as exc:
        await identity.revoke_membership(actor, own_id, idem=_idem("rev-self-2"))
    assert exc.value.code == "LAST_MANAGER"


async def test_provider_admin_rejects_pending_membership() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, customer=False, provider=True)
        admin = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="pa2"), org, role="provider_admin"
        )
        pending = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="pd2"),
            org,
            role="provider_dispatcher",
            status="pending",
        )
        actor = _actor(admin)
        pending_id = ids.encode("membership", pending.id)

    result = await identity.revoke_membership(actor, pending_id, idem=_idem("rej-1"))
    assert result.body["status"] == "revoked"

    with pytest.raises(Conflict):
        await identity.approve_membership(actor, pending_id, idem=_idem("rej-appr"))
    items, _ = await identity.list_members(scope_of(actor))
    assert {m.id: m.status for m in items}[pending_id] == "revoked"
