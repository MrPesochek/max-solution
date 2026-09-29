import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import AuditEntry, Invitation, Membership, Notification, Organization
from app.modules.identity import api as identity
from app.worker import notification_templates as templates
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


async def _customer_org() -> tuple[UserActor, Organization]:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id=uuid.uuid4().hex), org
        )
        return _actor(manager), org


async def _bare_user(max_user_id: str, name: str = "Сотрудник") -> BareUserActor:
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id=max_user_id, display_name=name)
        return BareUserActor(user.id)


async def _notifications(kind: str) -> list[Notification]:
    async with db_session.transaction() as s:
        return list(
            (
                await s.execute(select(Notification).where(Notification.notification_type == kind))
            ).scalars()
        )


async def _invite(
    actor: UserActor,
    key: str,
    *,
    recipient_max_user_id: str | None = None,
    recipient_name: str | None = None,
) -> dict[str, Any]:
    created = await identity.create_invitation(
        actor,
        identity.InvitationCreateData(
            role="customer_employee",
            recipient_max_user_id=recipient_max_user_id,
            recipient_name=recipient_name,
        ),
        idem=_idem(key),
    )
    return created.body


async def test_named_invitation_accepted_by_recipient_gives_access_at_once() -> None:
    actor, _ = await _customer_org()
    body = await _invite(actor, "n-1", recipient_max_user_id="max-42", recipient_name="Ольга")
    assert body["named"] is True
    assert body["recipient_name"] == "Ольга"

    accepted = await identity.accept_invitation(
        await _bare_user("max-42"), body["token"], idem=_idem("n-1a")
    )
    assert accepted.body["status"] == "active"
    assert await _notifications("membership.pending_approval") == []


async def test_named_invitation_rejects_other_user_without_consuming() -> None:
    actor, org = await _customer_org()
    body = await _invite(actor, "n-2", recipient_max_user_id="max-43")
    stranger = await _bare_user("max-stranger", "Посторонний")

    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(stranger, body["token"], idem=_idem("n-2a"))
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}
    assert (await identity.preview_invitation(body["token"])).state == "active"

    with pytest.raises(Conflict):
        await identity.accept_invitation(stranger, body["token"], idem=_idem("n-2b"))
    warned = await _notifications("invitation.foreign_attempt")
    assert [n.recipient_user_id for n in warned] == [actor.user_id]
    assert warned[0].organization_id == org.id
    assert warned[0].payload == {
        "invitation_id": body["id"],
        "user_id": ids.encode("user", stranger.user_id),
    }
    async with db_session.transaction() as s:
        attempts = (
            await s.execute(
                select(AuditEntry).where(AuditEntry.action == "invitation.accept_foreign")
            )
        ).scalars()
        assert len(list(attempts)) == 2
        assert (
            list(
                (
                    await s.execute(
                        select(Membership).where(Membership.user_id == stranger.user_id)
                    )
                ).scalars()
            )
            == []
        )

    accepted = await identity.accept_invitation(
        await _bare_user("max-43"), body["token"], idem=_idem("n-2c")
    )
    assert accepted.body["status"] == "active"


async def test_foreign_attempt_retry_with_same_key_is_not_replayed_as_success() -> None:
    """Отказ не сохраняется под ключом идемпотентности: повтор снова проверяет адресата."""
    actor, _ = await _customer_org()
    body = await _invite(actor, "n-3", recipient_max_user_id="max-44")
    stranger = await _bare_user("max-stranger-2")
    for _ in range(2):
        with pytest.raises(Conflict):
            await identity.accept_invitation(stranger, body["token"], idem=_idem("n-3a"))
    async with db_session.transaction() as s:
        invitation = await s.get(Invitation, ids.decode("invitation", body["id"]))
        assert invitation is not None and invitation.status == "pending"


async def test_open_invitation_waits_for_manager_and_manager_approves() -> None:
    actor, _ = await _customer_org()
    body = await _invite(actor, "o-1", recipient_name="Пётр Иванов")
    assert body["named"] is False

    accepted = await identity.accept_invitation(
        await _bare_user("max-50", "Пётр И."), body["token"], idem=_idem("o-1a")
    )
    assert accepted.body["status"] == "pending"

    pending = await _notifications("membership.pending_approval")
    assert [n.recipient_user_id for n in pending] == [actor.user_id]
    assert pending[0].payload == {"membership_id": accepted.body["id"]}

    members, _ = await identity.list_members(scope_of(actor))
    waiting = next(m for m in members if m.id == accepted.body["id"])
    assert waiting.user.display_name == "Пётр И."
    assert waiting.accepted_at is not None
    assert waiting.expected_name == "Пётр Иванов"

    approved = await identity.approve_membership(actor, accepted.body["id"], idem=_idem("o-1b"))
    assert approved.body["status"] == "active"
    approved_note = await _notifications("membership.approved")
    assert [n.recipient_user_id for n in approved_note] == [
        (await _membership_user(accepted.body["id"]))
    ]

    again = await identity.approve_membership(actor, accepted.body["id"], idem=_idem("o-1b"))
    assert again.body["status"] == "active"
    assert len(await _notifications("membership.approved")) == 1


async def _membership_user(public_id: str) -> uuid.UUID:
    async with db_session.transaction() as s:
        membership = await s.get(Membership, ids.decode("membership", public_id))
        assert membership is not None
        return membership.user_id


async def test_employee_cannot_approve_and_other_org_is_not_found() -> None:
    actor, org = await _customer_org()
    body = await _invite(actor, "o-2")
    accepted = await identity.accept_invitation(
        await _bare_user("max-51"), body["token"], idem=_idem("o-2a")
    )
    async with db_session.transaction() as s:
        employee = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="max-emp"), org, role="customer_employee"
        )
        other = await factories.create_organization(s, name="Чужая")
        other_manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="max-other"), other
        )

    with pytest.raises(Forbidden):
        await identity.approve_membership(_actor(employee), accepted.body["id"], idem=None)
    with pytest.raises(NotFound):
        await identity.approve_membership(_actor(other_manager), accepted.body["id"], idem=None)


async def test_recipient_fields_are_validated() -> None:
    actor, _ = await _customer_org()
    with pytest.raises(ValidationFailed):
        await _invite(actor, "v-1", recipient_max_user_id="два слова")
    with pytest.raises(ValidationFailed):
        await _invite(actor, "v-2", recipient_name="x" * 201)
    body = await _invite(actor, "v-3", recipient_max_user_id="  ", recipient_name=" ")
    assert body["named"] is False
    assert body["recipient_name"] is None


async def test_audit_of_create_does_not_store_recipient() -> None:
    actor, _ = await _customer_org()
    await _invite(actor, "a-1", recipient_max_user_id="max-secret", recipient_name="Имя")
    async with db_session.transaction() as s:
        entry = (
            await s.execute(select(AuditEntry).where(AuditEntry.action == "invitation.create"))
        ).scalar_one()
    assert entry.details == {"role": "customer_employee", "named": True}


async def _render(row: Notification) -> str:
    async with db_session.transaction() as s:
        message = await templates.render(
            s,
            row.notification_type,
            dict(row.payload),
            recipient_user_id=row.recipient_user_id,
            recipient_membership_id=row.recipient_membership_id,
            now=utcnow(),
        )
        assert message.skip_reason is None
        return message.text


async def test_notifications_name_the_accounts_from_max() -> None:
    actor, _ = await _customer_org()
    open_body = await _invite(actor, "t-1")
    accepted = await identity.accept_invitation(
        await _bare_user("max-60", "Анна К."), open_body["token"], idem=_idem("t-1a")
    )
    named_body = await _invite(actor, "t-2", recipient_max_user_id="max-61")
    with pytest.raises(Conflict):
        await identity.accept_invitation(
            await _bare_user("max-62", "Чужой Аккаунт"), named_body["token"], idem=_idem("t-2a")
        )
    await identity.approve_membership(actor, accepted.body["id"], idem=_idem("t-1b"))

    pending = (await _notifications("membership.pending_approval"))[0]
    foreign = (await _notifications("invitation.foreign_attempt"))[0]
    approved = (await _notifications("membership.approved"))[0]
    assert "Чужой Аккаунт" in await _render(foreign)
    assert "подтвердил" in await _render(approved)
    async with db_session.transaction() as s:
        stale = await templates.render(
            s,
            pending.notification_type,
            dict(pending.payload),
            recipient_user_id=pending.recipient_user_id,
            now=utcnow(),
        )
    assert stale.skip_reason == "membership_decided"


async def test_pending_approval_notification_names_account() -> None:
    actor, _ = await _customer_org()
    body = await _invite(actor, "t-3")
    await identity.accept_invitation(
        await _bare_user("max-63", "Анна К."), body["token"], idem=_idem("t-3a")
    )
    text = await _render((await _notifications("membership.pending_approval"))[0])
    assert "Ждёт подтверждения: Анна К." in text
