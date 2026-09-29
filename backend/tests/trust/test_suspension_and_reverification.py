import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import ids
from app.core.errors import Forbidden, InvalidTransition
from app.db import session as db_session
from app.db.models import (
    Assignment,
    AuditEntry,
    IntegrationClient,
    Organization,
    ProviderProfile,
    RepairRequest,
    ServiceBinding,
    VerificationCase,
)
from app.modules.requests import api as requests_api
from app.modules.trust import api as trust
from tests import factories
from tests.requests import factories as req_factories
from tests.requests import helpers as h
from tests.support import idem, make_operator, make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_suspension_revokes_pending_and_keeps_accepted_for_operator() -> None:
    world = await req_factories.build_world()
    pending = await h.make_submitted(world)
    accepted = await h.make_accepted(world)
    operator = await make_operator("op-release")

    await trust.suspend_provider(
        operator,
        ids.encode("organization", world.provider_org_id),
        "жалобы клиентов",
        idem=idem("release-1"),
    )

    revoked = await h.reload(Assignment, h.assignment_id(pending))
    assert revoked.state == "revoked"
    assert revoked.revoke_reason == "provider_suspended"
    request = await h.reload(RepairRequest, h.rid(pending))
    assert request.status == "action_required"
    events = [e for e in await h.integration_events() if e.event_type == "assignment.revoked"]
    assert [e.payload.get("reason_kind") for e in events] == ["provider_suspended"]

    kept = await h.reload(Assignment, h.assignment_id(accepted))
    assert kept.state == "accepted"
    supervised = await requests_api.supervised_assignments(operator)
    assert [row.request_id for row in supervised] == [accepted["id"]]
    with pytest.raises(Forbidden):
        await requests_api.supervised_assignments(world.manager)

    await trust.reinstate_provider(
        operator,
        ids.encode("organization", world.provider_org_id),
        "разобрались",
        idem=idem("release-2"),
    )
    assert await requests_api.supervised_assignments(operator) == []


async def test_live_binding_is_unique_per_equipment_and_provider() -> None:
    world = await req_factories.build_world()
    async with db_session.transaction() as session:
        existing = await session.get(ServiceBinding, world.binding_id)
        assert existing is not None
        duplicate = ServiceBinding(
            equipment_id=existing.equipment_id,
            customer_org_id=existing.customer_org_id,
            provider_org_id=existing.provider_org_id,
            basis=existing.basis,
            status="pending",
            created_by_membership_id=existing.created_by_membership_id,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError) as exc:
            await session.flush()
        assert "ux_service_bindings_live_equipment_provider" in str(exc.value)
        await session.rollback()
    async with db_session.transaction() as session:
        row = await session.get(ServiceBinding, world.binding_id)
        assert row is not None
        row.status = "revoked"
        session.add(
            ServiceBinding(
                equipment_id=row.equipment_id,
                customer_org_id=row.customer_org_id,
                provider_org_id=row.provider_org_id,
                basis=row.basis,
                status="pending",
                created_by_membership_id=row.created_by_membership_id,
            )
        )


async def test_operator_reopens_verification_and_revokes_access_on_compromise() -> None:
    provider = await make_provider("reopen", status="active", accepting=True, verified=True)
    operator = await make_operator("op-reopen")
    async with db_session.transaction() as session:
        org = await session.get(Organization, provider.organization_id)
        assert org is not None
        await factories.create_integration_client(session, org)

    organization_id = ids.encode("organization", provider.organization_id)
    with pytest.raises(Forbidden):
        await trust.reopen_verification(
            provider.admin, organization_id, "requisites", "смена реквизитов", idem=idem("r-0")
        )
    result = await trust.reopen_verification(
        operator,
        organization_id,
        "requisites",
        "Сменились реквизиты",
        compromise=True,
        idem=idem("r-1"),
    )
    assert [item["decision"] for item in result.body["items"]] == ["pending"]

    async with db_session.transaction() as session:
        profile = (
            await session.execute(
                select(ProviderProfile).where(
                    ProviderProfile.organization_id == provider.organization_id
                )
            )
        ).scalar_one()
        assert profile.status == "needs_information"
        keys = list(
            (
                await session.execute(
                    select(IntegrationClient.status).where(
                        IntegrationClient.provider_org_id == provider.organization_id
                    )
                )
            ).scalars()
        )
        assert keys == ["revoked"]
        cases = list(
            (
                await session.execute(
                    select(VerificationCase.decision).where(
                        VerificationCase.organization_id == provider.organization_id,
                        VerificationCase.check_kind == "requisites",
                    )
                )
            ).scalars()
        )
        assert "pending" in cases
        audit = (
            await session.execute(
                select(AuditEntry.details).where(
                    AuditEntry.action == "provider_profile.reopen_verification"
                )
            )
        ).scalar_one()
        assert audit["compromise"] is True and audit["revoked_api_keys"] == 1

    with pytest.raises(InvalidTransition):
        await trust.reopen_verification(
            operator, organization_id, "representative", "ещё раз", idem=idem("r-2")
        )


async def test_verification_notes_only_for_heads() -> None:
    world = await req_factories.build_world()
    async with db_session.transaction() as session:
        session.add_all(
            [
                VerificationCase(
                    organization_id=world.provider_org_id,
                    subject_type="organization_details",
                    check_kind="requisites",
                    decision="needs_information",
                    decision_reason="Нужна выписка",
                    evidence_note="Паспорт представителя: ...",
                ),
                VerificationCase(
                    organization_id=world.provider_org_id,
                    subject_type="customer_representative",
                    check_kind="customer_representative",
                    decision="pending",
                ),
            ]
        )
    full = await trust.list_verification_cases(world.provider_admin)
    assert [c.check_kind for c in full] == ["requisites"]
    assert full[0].evidence_note is not None and full[0].decision_reason == "Нужна выписка"

    trimmed = await trust.list_verification_cases(world.dispatcher)
    assert [c.check_kind for c in trimmed] == ["requisites"]
    assert trimmed[0].evidence_note is None
    assert trimmed[0].decision_reason is None
    assert trimmed[0].decision == "needs_information"
