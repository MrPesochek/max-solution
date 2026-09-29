import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import ids
from app.db import session as db_session
from app.db.models import Membership, Organization, PlatformRole, ProviderProfile, VerificationCase
from app.demo.seed import ORG_CUSTOMER, ORG_PROVIDER
from app.infra.config import Settings
from tests.requests import factories
from tests.support import session_token

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_showcase_requires_auth_and_explicit_enable(client: AsyncClient) -> None:
    assert (await client.post("/showcase/join", json={"side": "customer"})).status_code == 401
    world = await factories.build_world()
    headers = {"Authorization": f"Bearer {await session_token(world.manager)}"}
    assert (await client.get("/showcase", headers=headers)).json() == {"enabled": False}
    assert (
        await client.post("/showcase/join", headers=headers, json={"side": "customer"})
    ).status_code == 404


async def test_showcase_only_joins_fixed_demo_orgs_once(
    client: AsyncClient,
    settings: Settings,
) -> None:
    settings.demo_showcase_enabled = True
    world = await factories.build_world()
    headers = {"Authorization": f"Bearer {await session_token(world.manager)}"}
    async with db_session.transaction() as db:
        db.add(
            Organization(
                id=ORG_CUSTOMER, display_name="Демо: заказчик", legal_name="Демо", is_customer=True
            )
        )
        db.add(
            Organization(
                id=ORG_PROVIDER, display_name="Демо: сервис", legal_name="Демо", is_provider=True
            )
        )
    for side, org in (("customer", ORG_CUSTOMER), ("provider", ORG_PROVIDER)):
        first = await client.post("/showcase/join", headers=headers, json={"side": side})
        second = await client.post("/showcase/join", headers=headers, json={"side": side})
        assert first.status_code == 200, first.text
        assert first.json() == second.json()
        assert first.json()["organization"]["id"] == ids.encode("organization", org)
    assert (
        await client.post("/showcase/join", headers=headers, json={"side": "operator"})
    ).status_code == 422
    async with db_session.transaction() as db:
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.user_id == world.manager.user_id,
                    Membership.organization_id == ORG_CUSTOMER,
                )
            )
        ).scalar_one()
        membership.status = "revoked"
    response = await client.post("/showcase/join", headers=headers, json={"side": "customer"})
    assert response.status_code == 403


async def test_demo_verification_is_scoped_and_does_not_grant_platform_role(
    client: AsyncClient,
    settings: Settings,
) -> None:
    world = await factories.build_world()
    headers = {"Authorization": f"Bearer {await session_token(world.manager)}"}
    async with db_session.transaction() as db:
        db.add(
            Organization(
                id=ORG_PROVIDER, display_name="Демо: сервис", legal_name="Демо", is_provider=True
            )
        )
        await db.flush()
        db.add(
            ProviderProfile(
                organization_id=ORG_PROVIDER,
                provider_kind="company",
                status="pending_review",
            )
        )
        demo_case = VerificationCase(
            organization_id=ORG_PROVIDER,
            subject_type="organization_details",
            check_kind="requisites",
            is_demo=True,
        )
        real_case = VerificationCase(
            organization_id=world.manager.organization_id,
            subject_type="representative",
            check_kind="customer_representative",
        )
        db.add_all([demo_case, real_case])
        await db.flush()
        demo_id = ids.encode("verification_case", demo_case.id)
        real_id = ids.encode("verification_case", real_case.id)
    payload = {
        "decision": "approved",
        "reason": "Демо-проверка",
        "source": "Демо-реестр",
        "is_demo": False,
    }
    endpoint = f"/showcase/verification-cases/{demo_id}/decision"
    assert (await client.get("/showcase/verification-cases")).status_code == 401
    assert (await client.get("/showcase/verification-cases", headers=headers)).status_code == 404
    assert (
        await client.post(
            endpoint, headers={**headers, "Idempotency-Key": "demo-disabled-01"}, json=payload
        )
    ).status_code == 404
    settings.demo_showcase_enabled = True
    assert (await client.post(endpoint, json=payload)).status_code == 401
    queue = await client.get("/showcase/verification-cases?limit=1", headers=headers)
    assert queue.status_code == 200, queue.text
    assert [item["id"] for item in queue.json()["items"]] == [demo_id]
    assert queue.json()["next_cursor"] is None
    denied = await client.post(
        f"/showcase/verification-cases/{real_id}/decision",
        headers={**headers, "Idempotency-Key": "demo-scope-real-01"},
        json=payload,
    )
    assert denied.status_code == 404, denied.text
    result = await client.post(
        endpoint, headers={**headers, "Idempotency-Key": "demo-approve-01"}, json=payload
    )
    assert result.status_code == 200, result.text
    assert result.json()["is_demo"] is True
    assert result.json()["decision"] == "approved"
    repeated = await client.post(
        endpoint, headers={**headers, "Idempotency-Key": "demo-approve-01"}, json=payload
    )
    assert repeated.json() == result.json()
    assert (
        await client.get("http://testserver/operator-api/v1/verification-cases", headers=headers)
    ).status_code == 403
    async with db_session.transaction() as db:
        assert (
            not (
                await db.execute(
                    select(PlatformRole).where(PlatformRole.user_id == world.manager.user_id)
                )
            )
            .scalars()
            .all()
        )
        case = await db.get(VerificationCase, real_case.id)
        assert case.decision == "pending"
        demo = await db.get(VerificationCase, demo_case.id)
        assert demo.operator_user_id == world.manager.user_id
