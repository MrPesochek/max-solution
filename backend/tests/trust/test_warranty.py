import pytest
from sqlalchemy import select

from app.core import ids
from app.core.errors import Forbidden, ValidationFailed
from app.db import session as db_session
from app.db.models import AuditEntry, Organization, ServiceBinding
from app.modules.providers import api as providers
from app.modules.trust import api as trust
from tests import factories
from tests.support import (
    CUSTOMER_INN,
    OTHER_INN,
    idem,
    make_customer,
    make_operator,
    make_provider,
)

pytestmark = pytest.mark.usefixtures("clean_db")


def _data(provider_org_id, **overrides):
    payload = {
        "provider_organization_id": ids.encode("organization", provider_org_id),
        "guarantor_kind": "manufacturer",
        "guarantor_name": "Завод Холод",
        "source": "письмо производителя от 01.09",
        "reason": "подтверждено по независимому каналу выдавшей стороны",
        "brands": ["Бренд"],
    }
    payload.update(overrides)
    return trust.WarrantyAuthorizationData(**payload)


async def test_parties_cannot_grant_themselves_warranty_authority() -> None:
    provider = await make_provider("wa-self", status="active", accepting=True, verified=True)
    customer = await make_customer("wa-self-c")

    for actor in (provider.admin, provider.dispatcher, customer.manager):
        with pytest.raises(Forbidden):
            await trust.create_warranty_authorization(
                actor, _data(provider.organization_id), idem=idem(f"wa-self-{actor.role}")
            )

    view = await providers.get_public_profile(provider.organization_id)
    assert view.warranty_authorizations == []


async def test_operator_grants_authority_with_source_and_scope() -> None:
    provider = await make_provider("wa-op", status="active", accepting=True, verified=True)
    operator = await make_operator("op-wa")

    with pytest.raises(ValidationFailed):
        await trust.create_warranty_authorization(
            operator, _data(provider.organization_id, reason="  "), idem=idem("wa-op-0")
        )
    with pytest.raises(ValidationFailed):
        await trust.create_warranty_authorization(
            operator, _data(provider.organization_id, source=" "), idem=idem("wa-op-1")
        )

    result = await trust.create_warranty_authorization(
        operator, _data(provider.organization_id), idem=idem("wa-op-2")
    )
    assert result.status == 201
    assert result.body["brands"] == ["Бренд"]
    assert result.body["guarantor_kind"] == "manufacturer"

    view = await providers.get_public_profile(provider.organization_id)
    assert len(view.warranty_authorizations) == 1
    badge = view.warranty_authorizations[0]
    assert badge.guarantor_name == "Завод Холод"
    assert badge.is_demo is True

    async with db_session.transaction() as s:
        audit = list(
            (
                await s.execute(
                    select(AuditEntry).where(AuditEntry.action == "warranty_authorization.create")
                )
            ).scalars()
        )
    assert len(audit) == 1
    assert audit[0].details["reason"]

    await trust.revoke_warranty_authorization(
        operator, result.body["id"], "полномочия отозваны", idem=idem("wa-op-3")
    )
    view = await providers.get_public_profile(provider.organization_id)
    assert view.warranty_authorizations == []


async def test_warranty_binding_uses_authorized_source_and_is_not_transferred() -> None:
    authorized = await make_provider("wa-auth", status="active", accepting=True, verified=True)
    other = await make_provider(
        "wa-other", status="active", accepting=True, verified=True, inn=OTHER_INN
    )
    customer = await make_customer("wa-cust", verified=True)
    operator = await make_operator("op-wa-2")

    await trust.create_warranty_authorization(
        operator, _data(authorized.organization_id), idem=idem("wa-tr-1")
    )

    first = await _bind(authorized, customer, "Д-1", "wa-tr-2")
    assert first["guarantor_kind"] == "manufacturer"
    assert first["warranty_authorization"] is not None

    await trust.revoke_binding(customer.manager, first["id"], "смена мастера", idem=idem("wa-tr-3"))

    second = await _bind(other, customer, "Д-2", "wa-tr-4")
    assert second["warranty_authorization"] is None
    assert second["guarantor_kind"] == "service_org"

    async with db_session.transaction() as s:
        rows = list((await s.execute(select(ServiceBinding))).scalars())
    assert {row.status for row in rows} == {"revoked", "confirmed"}


async def _bind(provider, customer, number: str, key: str):
    issued = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=CUSTOMER_INN,
            contract_number=number,
            basis="warranty",
            equipment_items=[trust.BindingInvitationItem(description="Витрина")],
        ),
        idem=idem(f"{key}-inv"),
    )
    accepted = await trust.accept_binding_invitation(
        customer.manager,
        issued.body["token"],
        [
            trust.BindingItemMatch(
                item_index=0, equipment_id=ids.encode("equipment", customer.equipment_id)
            )
        ],
        idem=idem(f"{key}-acc"),
    )
    return accepted.body["items"][0]


async def test_revoked_authorization_is_not_matched() -> None:
    provider = await make_provider("wa-rev", status="active", accepting=True, verified=True)
    customer = await make_customer("wa-rev-c", verified=True)
    async with db_session.transaction() as s:
        org = await s.get(Organization, provider.organization_id)
        assert org is not None
        await factories.create_warranty_authorization(s, org, status="revoked")

    binding = await _bind(provider, customer, "Д-3", "wa-rev-1")
    assert binding["warranty_authorization"] is None
