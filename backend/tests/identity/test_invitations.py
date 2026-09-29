import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.pipeline import Idempotency, IdempotentSecretNotReplayable, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import (
    IdempotencyKey,
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    Organization,
    User,
)
from app.infra.crypto import hash_token
from app.modules.identity import api as identity
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="invitation", body_hash=hash_body({"k": key}))


def _actor(membership: Membership) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


async def _customer_org() -> tuple[UserActor, Organization, uuid.UUID]:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id=uuid.uuid4().hex), org
        )
        return _actor(manager), org, location.id


async def _bare_user(key: str) -> BareUserActor:
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id=key)
        return BareUserActor(user.id)


async def test_create_invitation_returns_token_once_and_links() -> None:
    actor, _, location_id = await _customer_org()
    result = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(role="customer_employee", location_ids=[location_id]),
        idem=_idem("inv-1"),
    )

    assert result.status == 201
    token = result.body["token"]
    assert len(token) >= 43
    assert result.body["state"] == "active"
    assert result.body["webapp_link"].startswith(f"https://max.ru/{factories.BOT_USERNAME}?")
    assert "startapp=inv_" in result.body["webapp_link"]
    assert "start=inv_" in result.body["bot_link"]

    async with db_session.transaction() as s:
        row = (await s.execute(select(Invitation))).scalar_one()
    assert row.token_prefix == hash_token(token).hex()[:8]
    assert row.token_prefix != token[:8]
    assert row.location_ids == [location_id]

    items, _cursor = await identity.list_invitations(scope_of(actor))
    assert [i.id for i in items] == [result.body["id"]]
    assert not hasattr(items[0], "token")

    async with db_session.transaction() as s:
        stored = (await s.execute(select(IdempotencyKey.response_body))).scalar_one()
    assert token not in str(stored)
    with pytest.raises(IdempotentSecretNotReplayable):
        await identity.create_invitation(
            actor,
            identity.InvitationCreateData(role="customer_employee", location_ids=[location_id]),
            idem=_idem("inv-1"),
        )


async def test_invitation_role_must_match_organization_side() -> None:
    actor, _, _ = await _customer_org()
    with pytest.raises(ValidationFailed):
        await identity.create_invitation(
            actor, identity.InvitationCreateData(role="provider_dispatcher"), idem=_idem("inv-2")
        )


async def test_invitation_locations_must_belong_to_organization() -> None:
    actor, _, _ = await _customer_org()
    async with db_session.transaction() as s:
        other = await factories.create_organization(s, name="Чужая")
        foreign = await factories.create_location(s, other)
        foreign_id = foreign.id

    with pytest.raises(NotFound):
        await identity.create_invitation(
            actor,
            identity.InvitationCreateData(role="customer_employee", location_ids=[foreign_id]),
            idem=_idem("inv-3"),
        )


async def test_employee_cannot_create_invitation() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        employee = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="e-inv"), org, role="customer_employee"
        )
        actor = _actor(employee)

    with pytest.raises(Forbidden):
        await identity.create_invitation(
            actor, identity.InvitationCreateData(role="customer_employee"), idem=_idem("inv-4")
        )


async def test_preview_does_not_consume_invitation() -> None:
    """A32: GET-предпросмотр не гасит приглашение."""
    actor, org, location_id = await _customer_org()
    created = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(role="customer_employee", location_ids=[location_id]),
        idem=_idem("inv-5"),
    )
    token = created.body["token"]

    first = await identity.preview_invitation(token)
    second = await identity.preview_invitation(token)
    assert first.state == second.state == "active"
    assert first.organization_name == org.display_name
    assert first.role == "customer_employee"

    async with db_session.transaction() as s:
        row = (await s.execute(select(Invitation))).scalar_one()
    assert row.status == "pending"
    assert row.accepted_at is None


async def test_accept_creates_membership_with_granted_locations() -> None:
    """A01: сотрудник получает ровно те точки, что указаны в приглашении.

    Приглашение именное — доступ открывается сразу, без подтверждения (ТЗ 6.5.4)."""
    actor, org, location_id = await _customer_org()
    created = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(
            role="customer_employee",
            location_ids=[location_id],
            recipient_max_user_id="invited-1",
        ),
        idem=_idem("inv-6"),
    )
    token = created.body["token"]
    invited = await _bare_user("invited-1")

    result = await identity.accept_invitation(invited, token, idem=_idem("acc-1"))
    assert result.status == 201
    assert result.body["status"] == "active"
    assert result.body["location_ids"] == [ids.encode("location", location_id)]

    async with db_session.transaction() as s:
        links = list((await s.execute(select(MembershipLocation.location_id))).scalars())
    assert links == [location_id]

    resolved = await identity.resolve_actor(
        identity.SessionInfo(
            session_id=uuid.uuid4(),
            user_id=invited.user_id,
            display_name="Сотрудник",
            expires_at=utcnow() + timedelta(hours=1),
        ),
        ids.encode("organization", org.id),
    )
    assert isinstance(resolved, UserActor)
    assert resolved.location_ids == frozenset({location_id})


async def test_used_invitation_does_not_work_again() -> None:
    actor, _, _ = await _customer_org()
    created = await identity.create_invitation(
        actor, identity.InvitationCreateData(role="customer_employee"), idem=_idem("inv-7")
    )
    token = created.body["token"]
    await identity.accept_invitation(await _bare_user("invited-2"), token, idem=_idem("acc-2"))

    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(await _bare_user("invited-3"), token, idem=_idem("acc-3"))
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}


async def test_revoked_invitation_does_not_work() -> None:
    actor, _, _ = await _customer_org()
    created = await identity.create_invitation(
        actor, identity.InvitationCreateData(role="customer_employee"), idem=_idem("inv-8")
    )
    await identity.revoke_invitation(actor, created.body["id"], idem=_idem("rvk-1"))

    preview = await identity.preview_invitation(created.body["token"])
    assert preview.state == "revoked"

    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(
            await _bare_user("invited-4"), created.body["token"], idem=_idem("acc-4")
        )
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}


async def test_expired_invitation_reports_expiry() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        _, token = await factories.create_invitation(
            s, org, expires_at=utcnow() - timedelta(minutes=1)
        )

    assert (await identity.preview_invitation(token)).state == "expired"
    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(await _bare_user("invited-5"), token, idem=_idem("acc-5"))
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {"reason": "expired"}


async def test_token_of_other_kind_is_rejected() -> None:
    """A32: приглашение привязки нельзя использовать как приглашение сотрудника."""
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        _, token = await factories.create_invitation(s, org, kind="service_binding", role=None)

    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(await _bare_user("invited-6"), token, idem=_idem("acc-6"))
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}

    with pytest.raises(NotFound):
        await identity.preview_invitation(token)


async def test_unknown_token_is_rejected_the_same_way() -> None:
    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(
            await _bare_user("invited-7"), "чужой-токен-которого-нет", idem=_idem("acc-7")
        )
    assert exc.value.code == "INVITATION_INVALID"


async def test_provider_membership_needs_admin_approval() -> None:
    """ТЗ 6.5.4: новый аккаунт исполнителя ждёт подтверждения администратором."""
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, customer=False, provider=True)
        admin = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="pa-inv"), org, role="provider_admin"
        )
        actor = _actor(admin)

    created = await identity.create_invitation(
        actor, identity.InvitationCreateData(role="provider_dispatcher"), idem=_idem("inv-9")
    )
    result = await identity.accept_invitation(
        await _bare_user("invited-8"), created.body["token"], idem=_idem("acc-8")
    )
    assert result.body["status"] == "pending"

    approved = await identity.approve_membership(actor, result.body["id"], idem=_idem("appr-9"))
    assert approved.body["status"] == "active"


async def test_invitation_of_other_organization_is_not_revocable() -> None:
    actor, _, _ = await _customer_org()
    async with db_session.transaction() as s:
        other = await factories.create_organization(s, name="Чужая")
        invitation, _token = await factories.create_invitation(s, other)
        foreign_id = ids.encode("invitation", invitation.id)

    with pytest.raises(NotFound):
        await identity.revoke_invitation(actor, foreign_id, idem=_idem("rvk-2"))

    items, _cursor = await identity.list_invitations(scope_of(actor))
    assert foreign_id not in [i.id for i in items]


async def test_concurrent_accepts_consume_token_once() -> None:
    """A32: конкурирующие подтверждения расходуют токен ровно один раз."""
    actor, _, _ = await _customer_org()
    created = await identity.create_invitation(
        actor, identity.InvitationCreateData(role="customer_employee"), idem=_idem("inv-10")
    )
    token = created.body["token"]
    first = await _bare_user("race-1")
    second = await _bare_user("race-2")

    results = await asyncio.gather(
        identity.accept_invitation(first, token, idem=_idem("race-a")),
        identity.accept_invitation(second, token, idem=_idem("race-b")),
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, Conflict)]
    assert len(ok) == 1
    assert len(failed) == 1
    assert failed[0].code == "INVITATION_INVALID"

    async with db_session.transaction() as s:
        memberships = list((await s.execute(select(Membership))).scalars())
    assert len([m for m in memberships if m.role == "customer_employee"]) == 1


async def test_invitation_without_role_belongs_to_customer_side() -> None:
    """Старое приглашение без роли принимается как сотрудник заказчика — и видно,
    и отзывается руководителем заказчика."""
    actor, org, _ = await _customer_org()
    async with db_session.transaction() as s:
        invitation, _token = await factories.create_invitation(s, org, role=None)  # type: ignore[arg-type]
        public_id = ids.encode("invitation", invitation.id)

    items, _cursor = await identity.list_invitations(scope_of(actor))
    assert public_id in [i.id for i in items]

    await identity.revoke_invitation(actor, public_id, idem=_idem("rvk-null"))
    async with db_session.transaction() as s:
        stored = await s.get(Invitation, invitation.id)
        assert stored is not None and stored.status == "revoked"


async def test_preview_names_inviter_and_role_locations() -> None:
    actor, _, location_id = await _customer_org()
    created = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(role="customer_employee", location_ids=[location_id]),
        idem=_idem("inv-names"),
    )
    preview = await identity.preview_invitation(created.body["token"])
    async with db_session.transaction() as s:
        location = await s.get(Location, location_id)
        membership = await s.get(Membership, actor.membership_id)
        assert location is not None and membership is not None
        inviter = await s.get(User, membership.user_id)
        assert inviter is not None
    assert preview.inviter_name == inviter.display_name
    assert preview.location_names == [location.name]


async def test_inactive_invitation_preview_shows_only_state() -> None:
    """Отозванное или использованное приглашение не раскрывает, кто и куда звал."""
    actor, _, location_id = await _customer_org()
    created = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(role="customer_employee", location_ids=[location_id]),
        idem=_idem("inv-state"),
    )
    await identity.revoke_invitation(actor, created.body["id"], idem=_idem("inv-state-r"))

    preview = await identity.preview_invitation(created.body["token"])
    assert preview.model_dump() == {
        "organization_name": None,
        "role": None,
        "expires_at": None,
        "state": "revoked",
        "inviter_name": None,
        "location_names": [],
    }
