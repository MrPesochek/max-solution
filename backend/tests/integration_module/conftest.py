import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import IntegrationActor, UserActor
from app.core.pipeline import Idempotency, hash_body
from app.db.models import IntegrationClient, Organization
from app.infra.config import Settings
from tests import factories


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.integration_settings(monkeypatch)


async def provider_org(session: AsyncSession, *, name: str = "ООО Сервис") -> Organization:
    org = await factories.create_organization(session, name=name, customer=False, provider=True)
    await factories.create_provider_profile(session, org)
    return org


async def provider_admin(session: AsyncSession, org: Organization) -> UserActor:
    user = await factories.create_user(session)
    membership = await factories.create_membership(session, user, org, role="provider_admin")
    return UserActor(
        user_id=user.id,
        membership_id=membership.id,
        organization_id=org.id,
        role="provider_admin",
    )


def integration_actor(
    client: IntegrationClient, scopes: frozenset[str] | None = None
) -> IntegrationActor:
    return IntegrationActor(
        integration_client_id=client.id,
        organization_id=client.provider_org_id,
        scopes=scopes if scopes is not None else frozenset(client.scopes),
    )


def idem(operation: str) -> Idempotency:
    return Idempotency(key=f"test-{uuid.uuid4().hex}", operation=operation, body_hash=hash_body({}))
