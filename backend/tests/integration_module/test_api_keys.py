import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import UserActor
from app.core.errors import Conflict, DomainError, Forbidden, Unauthenticated
from app.db.models import IntegrationClient, Notification, WebhookSubscription
from app.modules.integration import api as integration
from app.modules.integration.keys import issue_api_key, parse_api_key
from app.modules.integration.policy import SCOPES
from tests import factories
from tests.integration_module.conftest import idem, provider_admin, provider_org

pytestmark = pytest.mark.asyncio


async def test_create_returns_full_key_once(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    result = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read", "webhooks:manage"]),
        idem=idem("POST /integration/api-keys"),
    )

    assert result.status == 201
    raw = result.body["key"]
    parsed = parse_api_key(raw)
    assert parsed is not None
    assert raw.startswith("rk_test_")
    assert parsed.prefix == result.body["key_prefix"]

    keys = await integration.list_api_keys(admin)
    assert [k.key_prefix for k in keys] == [parsed.prefix]
    assert "key" not in keys[0].model_dump()


async def test_create_notifies_admins_and_audits(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
        idem=idem("POST /integration/api-keys"),
    )

    rows = list((await db_session.execute(select(Notification))).scalars())
    assert [r.notification_type for r in rows] == ["integration.api_key.created"]


async def test_unknown_scope_rejected(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    with pytest.raises(DomainError) as exc:
        await integration.create_api_key(
            admin,
            integration.ApiKeyCreateData(name="CRM", scopes=["requests:read", "billing:write"]),
            idem=idem("POST /integration/api-keys"),
        )
    assert exc.value.details["unknown"] == ["billing:write"]


async def test_dispatcher_cannot_create_key(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    user = await factories.create_user(db_session)
    membership = await factories.create_membership(
        db_session, user, org, role="provider_dispatcher"
    )
    await db_session.commit()
    actor = UserActor(
        user_id=user.id,
        membership_id=membership.id,
        organization_id=org.id,
        role="provider_dispatcher",
    )

    with pytest.raises(Forbidden):
        await integration.create_api_key(
            actor,
            integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
            idem=idem("POST /integration/api-keys"),
        )


async def test_authenticate_success(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, raw = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    actor = await integration.authenticate_api_key(raw)
    assert actor.integration_client_id == client.id
    assert actor.organization_id == org.id
    assert "webhooks:manage" in actor.scopes


@pytest.mark.parametrize("raw", ["", "nonsense", "rk_test_abc", "rk_test_zz_secret"])
async def test_authenticate_malformed(db_session: AsyncSession, raw: str) -> None:
    with pytest.raises(Unauthenticated):
        await integration.authenticate_api_key(raw)


async def test_authenticate_revoked_key(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, raw = await factories.create_integration_client(db_session, org, status="revoked")
    await db_session.commit()

    with pytest.raises(Unauthenticated):
        await integration.authenticate_api_key(raw)


@pytest.mark.parametrize("status", ["needs_information", "suspended", "rejected", "draft"])
async def test_authenticate_does_not_depend_on_provider_status(
    db_session: AsyncSession, status: str
) -> None:
    """Ключ подлинный — актор есть; что ему доступно, решает ядро (ТЗ 12, 6.5.3)."""
    org = await factories.create_organization(db_session, customer=False, provider=True)
    await factories.create_provider_profile(db_session, org, status=status)
    _, raw = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    actor = await integration.authenticate_api_key(raw)
    assert actor.organization_id == org.id


async def test_revoke_then_authenticate_fails(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    created = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(
            name="CRM", scopes=sorted(SCOPES - {"service_bindings:write"})
        ),
        idem=idem("POST /integration/api-keys"),
    )
    raw = created.body["key"]
    await integration.authenticate_api_key(raw)

    await integration.revoke_api_key(admin, created.body["id"], idem=idem("revoke"))
    with pytest.raises(Unauthenticated):
        await integration.authenticate_api_key(raw)

    with pytest.raises(Conflict):
        await integration.revoke_api_key(admin, created.body["id"], idem=idem("revoke-again"))


async def test_rotate_replaces_key_in_place(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    created = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
        idem=idem("POST /integration/api-keys"),
    )
    old_raw = created.body["key"]

    rotated = await integration.rotate_api_key(admin, created.body["id"], idem=idem("rotate"))
    new_raw = rotated.body["key"]
    assert new_raw != old_raw
    assert rotated.body["id"] == created.body["id"]

    with pytest.raises(Unauthenticated):
        await integration.authenticate_api_key(old_raw)
    actor = await integration.authenticate_api_key(new_raw)
    assert actor.organization_id == org.id

    clients = list((await db_session.execute(select(IntegrationClient))).scalars())
    assert len(clients) == 1


async def test_foreign_organization_cannot_touch_key(db_session: AsyncSession) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    admin_a = await provider_admin(db_session, org_a)
    admin_b = await provider_admin(db_session, org_b)
    await db_session.commit()

    created = await integration.create_api_key(
        admin_a,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
        idem=idem("POST /integration/api-keys"),
    )

    with pytest.raises(DomainError) as exc:
        await integration.revoke_api_key(admin_b, created.body["id"], idem=idem("revoke"))
    assert exc.value.status == 404


async def test_list_api_keys_requires_provider_admin(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    user = await factories.create_user(db_session)
    membership = await factories.create_membership(
        db_session, user, org, role="provider_dispatcher"
    )
    await db_session.commit()
    dispatcher = UserActor(
        user_id=user.id,
        membership_id=membership.id,
        organization_id=org.id,
        role="provider_dispatcher",
    )

    with pytest.raises(Forbidden):
        await integration.list_api_keys(dispatcher)


async def test_key_of_other_environment_rejected(db_session: AsyncSession) -> None:
    """L11: demo-ключ не открывает рабочий контур и наоборот."""
    org = await provider_org(db_session)
    issued = issue_api_key("demo")
    client, _ = await factories.create_integration_client(db_session, org)
    client.api_key_hash = issued.digest
    client.api_key_prefix = issued.prefix
    await db_session.commit()

    with pytest.raises(Unauthenticated):
        await integration.authenticate_api_key(issued.raw)


async def test_revoke_disables_client_subscriptions(db_session: AsyncSession) -> None:
    """M4: отозванный ключ перестаёт получать вебхуки."""
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    client, _ = await factories.create_integration_client(db_session, org)
    other, _ = await factories.create_integration_client(db_session, org, name="Другая CRM")
    own = await factories.create_webhook_subscription(db_session, client)
    foreign = await factories.create_webhook_subscription(db_session, other)
    await db_session.commit()

    await integration.revoke_api_key(
        admin, ids.encode("integration_client", client.id), idem=idem("revoke")
    )

    await db_session.refresh(own)
    await db_session.refresh(foreign)
    assert own.status == "disabled"
    assert own.disabled_at is not None
    assert foreign.status == "active"
    assert (await db_session.get(WebhookSubscription, foreign.id)) is not None
