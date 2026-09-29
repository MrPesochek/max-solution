import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Invitation, Membership, Notification
from app.demo import seed
from app.modules.identity import api as identity

pytestmark = pytest.mark.usefixtures("clean_db")


def _customer_manager() -> UserActor:
    return UserActor(
        user_id=seed._id("user:manager"),
        membership_id=seed._id("membership:customer:manager"),
        organization_id=seed.ORG_CUSTOMER,
        role="customer_manager",
    )


def _outsider() -> BareUserActor:
    return BareUserActor(seed._id("user:outsider_manager"))


async def _outsider_can_open_customer_org() -> bool:
    try:
        await identity.resolve_actor(
            identity.SessionInfo(
                session_id=uuid.uuid4(),
                user_id=seed._id("user:outsider_manager"),
                display_name="Посторонний",
                expires_at=utcnow() + timedelta(hours=1),
            ),
            ids.encode("organization", seed.ORG_CUSTOMER),
        )
    except NotFound:
        return False
    return True


async def test_forwarded_link_does_not_give_outsider_active_access() -> None:
    await seed.run()
    created = await identity.create_invitation(
        _customer_manager(), identity.InvitationCreateData(role="customer_employee"), idem=None
    )

    accepted = await identity.accept_invitation(_outsider(), created.body["token"], idem=None)

    assert accepted.body["status"] == "pending"
    assert accepted.body["role"] == "customer_employee"
    assert not await _outsider_can_open_customer_org()

    members, _ = await identity.list_members(scope_of(_customer_manager()))
    waiting = next(m for m in members if m.id == accepted.body["id"])
    assert waiting.status == "pending"
    assert waiting.user.display_name == "Демо: Руководитель чужой организации"
    assert waiting.accepted_at is not None

    rejected = await identity.revoke_membership(_customer_manager(), waiting.id, idem=None)
    assert rejected.body["status"] == "revoked"
    assert not await _outsider_can_open_customer_org()


async def test_named_invitation_rejects_outsider_and_stays_usable() -> None:
    await seed.run()
    created = await identity.create_invitation(
        _customer_manager(),
        identity.InvitationCreateData(
            role="customer_employee",
            recipient_max_user_id="demo-new-employee",
            recipient_name="Новый сотрудник",
        ),
        idem=None,
    )

    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(_outsider(), created.body["token"], idem=None)
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}
    assert not await _outsider_can_open_customer_org()

    async with db_session.transaction() as s:
        invitation = await s.get(Invitation, ids.decode("invitation", created.body["id"]))
        assert invitation is not None
        assert invitation.status == "pending"
        assert invitation.accepted_by_user_id is None
        outsider_memberships = (
            await s.execute(
                select(Membership).where(
                    Membership.user_id == seed._id("user:outsider_manager"),
                    Membership.organization_id == seed.ORG_CUSTOMER,
                )
            )
        ).scalars()
        assert list(outsider_memberships) == []
        warned = list(
            (
                await s.execute(
                    select(Notification.recipient_user_id).where(
                        Notification.notification_type == "invitation.foreign_attempt"
                    )
                )
            ).scalars()
        )
    assert warned == [seed._id("user:manager")]
