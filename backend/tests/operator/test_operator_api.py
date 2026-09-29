import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import ids
from app.db import session as db_session
from app.db.models import (
    AuditEntry,
    Equipment,
    Membership,
    Organization,
    User,
    VerificationCase,
)
from app.modules.providers import api as providers
from tests import factories
from tests.operator.conftest import auth, idem_header
from tests.support import idem, make_customer, make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def _session_token(max_user_id: str, *, operator: bool) -> str:
    async with db_session.transaction() as s:
        user = (
            await s.execute(select(User).where(User.max_user_id == max_user_id))
        ).scalar_one_or_none() or await factories.create_user(s, max_user_id=max_user_id)
        if operator:
            await factories.create_platform_role(s, user)
        return await factories.create_session_token(s, user)


async def test_operator_api_is_closed_without_platform_role(client: AsyncClient) -> None:
    assert (await client.get("/verification-cases")).status_code == 401
    assert (
        await client.get("/verification-cases", headers=auth("no-such-token"))
    ).status_code == 401

    plain = await _session_token("op-plain", operator=False)
    for path in ("/verification-cases", "/provider-profiles", "/service-bindings"):
        assert (await client.get(path, headers=auth(plain))).status_code == 403

    response = await client.post(
        "/verification-cases/ver_0000000000000000000000/decision",
        headers={**auth(plain), **idem_header("1")},
        json={"decision": "approved", "reason": "нет", "source": "нет"},
    )
    assert response.status_code == 403


async def test_operator_reviews_queue_and_decides(client: AsyncClient) -> None:
    provider = await make_provider("op-http")
    await providers.submit_for_review(provider.admin, idem=idem("op-http-submit"))
    token = await _session_token("op-http-user", operator=True)

    queue = await client.get(
        "/verification-cases", params={"decision": "pending"}, headers=auth(token)
    )
    assert queue.status_code == 200
    items = queue.json()["items"]
    assert {item["check_kind"] for item in items} == {"requisites", "representative"}
    assert items[0]["organization_name"] == "ООО Сервис"

    card = await client.get(f"/verification-cases/{items[0]['id']}", headers=auth(token))
    assert card.status_code == 200
    assert "evidence_note" in card.json()

    bad = await client.post(
        f"/verification-cases/{items[0]['id']}/decision",
        headers={**auth(token), **idem_header("2")},
        json={"decision": "approved", "reason": "", "source": "ЕГРЮЛ"},
    )
    assert bad.status_code == 422

    for index, item in enumerate(items):
        ok = await client.post(
            f"/verification-cases/{item['id']}/decision",
            headers={**auth(token), **idem_header(f"dec-{index}")},
            json={
                "decision": "approved",
                "reason": "проверено по независимому источнику",
                "source": "ЕГРЮЛ",
            },
        )
        assert ok.status_code == 200, ok.text

    profiles = await client.get(
        "/provider-profiles", params={"status": "active"}, headers=auth(token)
    )
    assert [p["organization_id"] for p in profiles.json()["items"]] == [
        ids.encode("organization", provider.organization_id)
    ]


async def test_operator_suspends_and_revokes_binding(client: AsyncClient) -> None:
    provider = await make_provider("op-susp-http", status="active", accepting=True, verified=True)
    customer = await make_customer("op-susp-cust")
    token = await _session_token("op-susp-user", operator=True)
    organization_id = ids.encode("organization", provider.organization_id)

    async with db_session.transaction() as s:
        equipment = await s.get(Equipment, customer.equipment_id)
        customer_org = await s.get(Organization, customer.organization_id)
        provider_org = await s.get(Organization, provider.organization_id)
        assert equipment is not None and customer_org is not None and provider_org is not None
        membership = await s.get(Membership, customer.manager.membership_id)
        assert membership is not None
        binding = await factories.create_service_binding(
            s, equipment, customer_org, membership, provider=provider_org
        )
        binding_id = ids.encode("service_binding", binding.id)

    disputed = await client.get(
        "/service-bindings", params={"status": "pending"}, headers=auth(token)
    )
    assert [row["id"] for row in disputed.json()["items"]] == [binding_id]
    assert disputed.json()["items"][0]["provider_name"] == "ООО Сервис"

    revoked = await client.post(
        f"/service-bindings/{binding_id}/revoke",
        headers={**auth(token), **idem_header("rev")},
        json={"reason": "спор разрешён в пользу заказчика"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    suspended = await client.post(
        f"/provider-profiles/{organization_id}/suspend",
        headers={**auth(token), **idem_header("susp")},
        json={"reason": "проверка по жалобе"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    async with db_session.transaction() as s:
        actions = {
            row.action
            for row in (await s.execute(select(AuditEntry))).scalars()
            if row.action.startswith(("provider_profile", "service_binding"))
        }
    assert "provider_profile.suspend" in actions
    assert "service_binding.revoke" in actions


async def test_warranty_authorization_via_operator_api(client: AsyncClient) -> None:
    provider = await make_provider("op-wa-http", status="active", accepting=True, verified=True)
    token = await _session_token("op-wa-user", operator=True)

    created = await client.post(
        "/warranty-authorizations",
        headers={**auth(token), **idem_header("wa")},
        json={
            "provider_organization_id": ids.encode("organization", provider.organization_id),
            "guarantor_kind": "manufacturer",
            "guarantor_name": "Завод",
            "source": "письмо производителя",
            "reason": "проверено у выдавшей стороны",
            "brands": ["Бренд"],
        },
    )
    assert created.status_code == 201, created.text
    listing = await client.get("/warranty-authorizations", headers=auth(token))
    assert [row["id"] for row in listing.json()["items"]] == [created.json()["id"]]

    async with db_session.transaction() as s:
        cases = list(
            (
                await s.execute(
                    select(VerificationCase).where(
                        VerificationCase.check_kind == "warranty_authorization"
                    )
                )
            ).scalars()
        )
    assert len(cases) == 1
    assert cases[0].decision == "approved"
    assert cases[0].source is not None


async def test_operator_support_endpoints(client: AsyncClient) -> None:
    """ТЗ 3, 6.5.3, 11.7: журнал доставок любой организации, принятые работы
    заблокированных исполнителей, повторная проверка и журнал чтения дела."""
    provider = await make_provider("op-support", status="active", accepting=True, verified=True)
    token = await _session_token("op-support-user", operator=True)
    plain = await _session_token("op-support-plain", operator=False)
    org_id = ids.encode("organization", provider.organization_id)

    deliveries = await client.get(
        "/deliveries", params={"organization_id": org_id}, headers=auth(token)
    )
    assert deliveries.status_code == 200
    assert deliveries.json()["items"] == []
    supervised = await client.get("/supervised-assignments", headers=auth(token))
    assert supervised.status_code == 200 and supervised.json() == []
    for path in ("/supervised-assignments", f"/deliveries?organization_id={org_id}"):
        assert (await client.get(path, headers=auth(plain))).status_code == 403

    reopened = await client.post(
        f"/provider-profiles/{org_id}/reopen-verification",
        headers={**auth(token), **idem_header("reopen-1")},
        json={"check_kind": "representative", "reason": "Сменился директор"},
    )
    assert reopened.status_code == 200, reopened.text
    case_id = reopened.json()["items"][0]["id"]
    card = await client.get(f"/verification-cases/{case_id}", headers=auth(token))
    assert card.status_code == 200
    async with db_session.transaction() as s:
        reads = (
            (
                await s.execute(
                    select(AuditEntry).where(AuditEntry.action == "verification_case.read")
                )
            )
            .scalars()
            .all()
        )
    assert len(reads) == 1
