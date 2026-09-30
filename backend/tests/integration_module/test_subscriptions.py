import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, DomainError, Forbidden
from app.infra.config import get_settings
from app.infra.crypto import SecretBox
from app.modules.integration import api as integration
from tests import factories
from tests.integration_module.conftest import (
    idem,
    integration_actor,
    provider_admin,
    provider_org,
)

pytestmark = pytest.mark.asyncio

CREATE = "POST /webhook-subscriptions"


async def test_create_returns_secret_once(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    actor = integration_actor(client)

    result = await integration.create_subscription(
        actor,
        integration.SubscriptionCreateData(
            url="https://crm.example.com/hooks", events=["request.assigned"]
        ),
        idem=idem(CREATE),
    )

    assert result.status == 201
    assert result.body["secret"]
    assert result.body["events"] == ["request.assigned"]

    listed = await integration.list_subscriptions(actor)
    assert len(listed) == 1
    assert "secret" not in listed[0].model_dump()


async def test_empty_event_list_means_all_types(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    result = await integration.create_subscription(
        integration_actor(client),
        integration.SubscriptionCreateData(url="https://crm.example.com/hooks", events=[]),
        idem=idem(CREATE),
    )
    assert set(result.body["events"]) == set(integration.EVENT_TYPES)


async def test_unknown_event_type_rejected(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    with pytest.raises(DomainError) as exc:
        await integration.create_subscription(
            integration_actor(client),
            integration.SubscriptionCreateData(
                url="https://crm.example.com/hooks", events=["request.exploded"]
            ),
            idem=idem(CREATE),
        )
    assert exc.value.details["unknown"] == ["request.exploded"]


@pytest.mark.parametrize(
    "url",
    [
        "http://crm.example.com/hooks",
        "https://127.0.0.1/hooks",
        "https://10.1.2.3/hooks",
        "ftp://crm.example.com/hooks",
        "https://user:pass@crm.example.com/hooks",
    ],
)
async def test_ssrf_unsafe_url_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("ALLOWED_PRIVATE_WEBHOOK_HOSTS", "")
    get_settings.cache_clear()
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    with pytest.raises(DomainError) as exc:
        await integration.create_subscription(
            integration_actor(client),
            integration.SubscriptionCreateData(url=url, events=["request.assigned"]),
            idem=idem(CREATE),
        )
    assert exc.value.code == "WEBHOOK_URL_REJECTED"


async def test_scope_required(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org, scopes=["requests:read"])
    await db_session.commit()

    with pytest.raises(Forbidden) as exc:
        await integration.create_subscription(
            integration_actor(client),
            integration.SubscriptionCreateData(url="https://crm.example.com/hooks"),
            idem=idem(CREATE),
        )
    assert exc.value.code == "INSUFFICIENT_SCOPE"


async def test_rotate_secret_changes_stored_value(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    subscription = await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()
    public_id = (await integration.list_subscriptions(integration_actor(client)))[0].id

    rotated = await integration.rotate_subscription_secret(
        integration_actor(client), public_id, idem=idem("rotate")
    )
    new_secret = rotated.body["secret"]
    assert new_secret != "test-webhook-secret"

    await db_session.refresh(subscription)
    box = SecretBox(factories.SECRETS_ENCRYPTION_KEY)
    assert box.decrypt(subscription.secret_encrypted).decode() == new_secret


async def test_delete_disables_subscription(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()
    actor = integration_actor(client)
    public_id = (await integration.list_subscriptions(actor))[0].id

    result = await integration.delete_subscription(actor, public_id, idem=idem("delete"))
    assert result.body["status"] == "disabled"

    with pytest.raises(Conflict):
        await integration.delete_subscription(actor, public_id, idem=idem("delete-again"))


async def test_foreign_organization_sees_no_subscription(db_session: AsyncSession) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    client_a, _ = await factories.create_integration_client(db_session, org_a)
    client_b, _ = await factories.create_integration_client(db_session, org_b)
    await factories.create_webhook_subscription(db_session, client_a)
    await db_session.commit()

    public_id = (await integration.list_subscriptions(integration_actor(client_a)))[0].id
    assert await integration.list_subscriptions(integration_actor(client_b)) == []

    with pytest.raises(DomainError) as exc:
        await integration.delete_subscription(
            integration_actor(client_b), public_id, idem=idem("delete")
        )
    assert exc.value.status == 404


async def test_provider_admin_manages_subscriptions_via_user_api(
    db_session: AsyncSession,
) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()

    access = integration.webhook_access(admin)
    assert access.organization_id == org.id
    listed = await integration.list_subscriptions(admin)
    assert len(listed) == 1


async def test_key_manages_only_own_subscriptions(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    client_a, _ = await factories.create_integration_client(db_session, org, name="A")
    client_b, _ = await factories.create_integration_client(db_session, org, name="B")
    await factories.create_webhook_subscription(db_session, client_a)
    await db_session.commit()
    actor_b = integration_actor(client_b)

    assert await integration.list_subscriptions(actor_b) == []
    public_id = (await integration.list_subscriptions(integration_actor(client_a)))[0].id
    for call in (
        integration.delete_subscription(actor_b, public_id, idem=idem("delete")),
        integration.rotate_subscription_secret(actor_b, public_id, idem=idem("rotate")),
        integration.send_test(actor_b, public_id),
    ):
        with pytest.raises(DomainError) as exc:
            await call
        assert exc.value.status == 404
    assert len(await integration.list_subscriptions(admin)) == 1


async def test_test_delivery_crash_does_not_leave_key_in_progress(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.integration import ping

    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()
    actor = integration_actor(client)
    public_id = (await integration.list_subscriptions(actor))[0].id
    key = idem("POST /webhook-subscriptions/test")

    async def crash(*args: object, **kwargs: object) -> object:
        raise RuntimeError("транспорт упал")

    monkeypatch.setattr(ping.transport, "deliver", crash)
    with pytest.raises(RuntimeError):
        await integration.send_test(actor, public_id, idem=key)

    async def delivered(*args: object, **kwargs: object) -> object:
        return ping.transport.AttemptResult(outcome="delivered", status_code=200)

    monkeypatch.setattr(ping.transport, "deliver", delivered)
    retried = await integration.send_test(actor, public_id, idem=key)
    assert retried.delivered is True
    assert retried.error is None
