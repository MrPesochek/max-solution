import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import UserActor
from app.core.errors import DomainError, Forbidden
from app.core.pipeline import IdempotentSecretNotReplayable
from app.db.models import AuditEntry, IdempotencyKey, IntegrationClient
from app.modules.integration import api as integration
from app.modules.integration.keys import issue_api_key
from tests import factories
from tests.integration_module.conftest import idem, provider_admin, provider_org

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("neighbour", ["requests:write", "marketplace:write"])
async def test_bindings_write_with_processing_scope_rejected(
    db_session: AsyncSession, neighbour: str
) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    with pytest.raises(DomainError) as exc:
        await integration.create_api_key(
            admin,
            integration.ApiKeyCreateData(name="CRM", scopes=["service_bindings:write", neighbour]),
            idem=idem("POST /integration/api-keys"),
        )
    assert exc.value.status == 422
    assert exc.value.code == "SCOPE_CONFLICT"
    assert exc.value.details["conflicting"] == [neighbour]
    assert (await db_session.execute(select(IntegrationClient))).first() is None


async def test_separate_bindings_key_allowed(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    result = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(
            name="Привязки", scopes=["service_bindings:write", "service_bindings:read"]
        ),
        idem=idem("POST /integration/api-keys"),
    )
    assert result.status == 201
    assert result.body["warnings"] == []


async def test_dispatcher_cannot_create_bindings_key(db_session: AsyncSession) -> None:
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
            integration.ApiKeyCreateData(name="CRM", scopes=["service_bindings:write"]),
            idem=idem("POST /integration/api-keys"),
        )


async def test_legacy_shared_key_gets_warning(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    issued = issue_api_key()
    db_session.add(
        IntegrationClient(
            provider_org_id=org.id,
            name="Старый",
            api_key_hash=issued.digest,
            api_key_prefix=issued.prefix,
            scopes=["requests:write", "service_bindings:write"],
            status="active",
        )
    )
    await db_session.commit()

    keys = await integration.list_api_keys(admin)
    assert keys[0].warnings == ["service_bindings_write_shared"]


async def test_full_key_is_never_stored_or_listed(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()

    request_idem = idem("POST /integration/api-keys")
    created = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
        idem=request_idem,
    )
    raw = created.body["key"]
    rotated = await integration.rotate_api_key(admin, created.body["id"], idem=idem("rotate"))
    raw_rotated = rotated.body["key"]

    with pytest.raises(IdempotentSecretNotReplayable):
        await integration.create_api_key(
            admin,
            integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
            idem=request_idem,
        )

    listed = [k.model_dump_json() for k in await integration.list_api_keys(admin)]
    stored = [
        str(row.response_body)
        for row in (await db_session.execute(select(IdempotencyKey))).scalars()
    ]
    audit = [str(row.details) for row in (await db_session.execute(select(AuditEntry))).scalars()]
    for secret in (raw, raw_rotated):
        secret_part = secret.split("_", 3)[3]
        for blob in (*listed, *stored, *audit):
            assert secret not in blob
            assert secret_part not in blob
