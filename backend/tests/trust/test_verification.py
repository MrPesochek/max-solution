from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.clock import set_clock, utcnow
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import (
    Assignment,
    AuditEntry,
    Notification,
    Organization,
    ProviderProfile,
    RepairRequest,
    VerificationCase,
)
from app.modules.providers import api as providers
from app.modules.trust import api as trust
from tests.support import PROVIDER_INN, idem, make_customer, make_operator, make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def _submitted_provider(key: str, *, inn: str | None = PROVIDER_INN):  # type: ignore[no-untyped-def]
    provider = await make_provider(key, inn=inn)
    await providers.submit_for_review(provider.admin, idem=idem(f"{key}-submit"))
    return provider


async def _cases(organization_id) -> dict[str, VerificationCase]:  # type: ignore[no-untyped-def]
    async with db_session.transaction() as s:
        rows = list(
            (
                await s.execute(
                    select(VerificationCase).where(
                        VerificationCase.organization_id == organization_id
                    )
                )
            ).scalars()
        )
    return {row.check_kind: row for row in rows}


async def _profile_status(organization_id) -> str:  # type: ignore[no-untyped-def]
    async with db_session.transaction() as s:
        profile = (
            await s.execute(
                select(ProviderProfile).where(ProviderProfile.organization_id == organization_id)
            )
        ).scalar_one()
        return profile.status


async def test_decision_requires_reason_and_source() -> None:
    """A37: решение оператора невозможно без основания, допуск — без источника."""
    provider = await _submitted_provider("ver-reason")
    operator = await make_operator("op-reason")
    case = (await _cases(provider.organization_id))["requisites"]
    case_id = ids.encode("verification_case", case.id)

    with pytest.raises(ValidationFailed):
        await trust.decide_verification_case(
            operator,
            case_id,
            trust.VerificationDecisionData(decision="approved", reason="  "),
            idem=idem("ver-r1"),
        )
    with pytest.raises(ValidationFailed):
        await trust.decide_verification_case(
            operator,
            case_id,
            trust.VerificationDecisionData(decision="approved", reason="ок", source=" "),
            idem=idem("ver-r2"),
        )


async def test_profile_becomes_active_only_after_both_checks() -> None:
    """A02/A30: допуск требует и реквизитов, и подтверждённого представителя."""
    provider = await _submitted_provider("ver-both")
    operator = await make_operator("op-both")
    cases = await _cases(provider.organization_id)

    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", cases["requisites"].id),
        trust.VerificationDecisionData(
            decision="approved", reason="выписка ЕГРЮЛ от 01.09", source="ЕГРЮЛ"
        ),
        idem=idem("ver-b1"),
    )
    assert await _profile_status(provider.organization_id) == "pending_review"

    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", cases["representative"].id),
        trust.VerificationDecisionData(
            decision="approved",
            reason="обратный звонок по номеру из независимого источника",
            source="обратный звонок",
        ),
        idem=idem("ver-b2"),
    )
    assert await _profile_status(provider.organization_id) == "active"

    view = await providers.get_public_profile(provider.organization_id)
    kinds = {badge.kind: badge for badge in view.verification}
    assert kinds["requisites"].confirmed and kinds["representative"].confirmed
    assert kinds["requisites"].is_demo is True
    assert kinds["requisites"].checked_at is not None

    async with db_session.transaction() as s:
        audit = list(
            (
                await s.execute(
                    select(AuditEntry).where(AuditEntry.action == "verification.decide")
                )
            ).scalars()
        )
    assert len(audit) == 2
    assert all(entry.details.get("reason") for entry in audit)


async def test_needs_information_returns_profile_and_accepts_answer() -> None:
    provider = await _submitted_provider("ver-need")
    operator = await make_operator("op-need")
    cases = await _cases(provider.organization_id)

    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", cases["representative"].id),
        trust.VerificationDecisionData(
            decision="needs_information", reason="нужен независимый канал связи"
        ),
        idem=idem("ver-n1"),
    )
    assert await _profile_status(provider.organization_id) == "needs_information"

    await trust.submit_verification_information(
        provider.admin,
        trust.VerificationInformationData(
            note="телефон приёмной из реестра", attachment_refs=["doc-1"]
        ),
        idem=idem("ver-n2"),
    )
    assert await _profile_status(provider.organization_id) == "pending_review"

    own = await trust.list_verification_cases(provider.admin)
    assert any("doc-1" in (case.evidence_note or "") for case in own)


async def test_rejection_keeps_reason_and_closes_requests() -> None:
    provider = await _submitted_provider("ver-rej")
    operator = await make_operator("op-rej")
    cases = await _cases(provider.organization_id)

    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", cases["requisites"].id),
        trust.VerificationDecisionData(decision="rejected", reason="реквизиты не подтверждены"),
        idem=idem("ver-rj"),
    )
    assert await _profile_status(provider.organization_id) == "rejected"
    profile = await providers.get_own_profile(scope_of(provider.admin))
    assert profile.status_reason == "реквизиты не подтверждены"
    assert profile.accepting_new_requests is False


async def test_second_provider_with_same_inn_is_domain_conflict() -> None:
    """A30: один подтверждённый профиль на ИНН; чужие данные не раскрываются."""
    first = await _submitted_provider("ver-inn-1")
    second = await _submitted_provider("ver-inn-2")
    operator = await make_operator("op-inn")

    first_cases = await _cases(first.organization_id)
    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", first_cases["requisites"].id),
        trust.VerificationDecisionData(decision="approved", reason="ЕГРЮЛ", source="ЕГРЮЛ"),
        idem=idem("ver-inn-a"),
    )

    second_cases = await _cases(second.organization_id)
    with pytest.raises(Conflict) as exc:
        await trust.decide_verification_case(
            operator,
            ids.encode("verification_case", second_cases["requisites"].id),
            trust.VerificationDecisionData(decision="approved", reason="ЕГРЮЛ", source="ЕГРЮЛ"),
            idem=idem("ver-inn-b"),
        )
    assert exc.value.code == "INN_ALREADY_VERIFIED"
    assert "ООО Сервис" not in exc.value.message
    assert await _profile_status(second.organization_id) == "pending_review"


async def test_only_operator_decides() -> None:
    provider = await _submitted_provider("ver-role")
    case = (await _cases(provider.organization_id))["requisites"]
    for actor in (provider.admin, (await make_customer("ver-role-c")).manager):
        with pytest.raises(Forbidden):
            await trust.decide_verification_case(
                actor,
                ids.encode("verification_case", case.id),
                trust.VerificationDecisionData(decision="approved", reason="я сам", source="сам"),
                idem=idem(f"ver-role-{actor.role}"),
            )


async def test_suspend_closes_new_requests_and_notifies_active_customers() -> None:
    """D28: заказчик с активной работой узнаёт о потере статуса исполнителем."""
    provider = await make_provider("ver-susp", status="active", accepting=True, verified=True)
    customer = await make_customer("ver-susp-c")
    operator = await make_operator("op-susp")

    async with db_session.transaction() as s:
        request = RepairRequest(
            customer_org_id=customer.organization_id,
            location_id=customer.location_id,
            equipment_id=customer.equipment_id,
            author_membership_id=customer.manager.membership_id,
            route="own_service",
            status="accepted",
        )
        s.add(request)
        await s.flush()
        s.add(
            Assignment(
                request_id=request.id,
                provider_org_id=provider.organization_id,
                route="own_service",
                state="accepted",
            )
        )

    organization_id = ids.encode("organization", provider.organization_id)
    await trust.suspend_provider(operator, organization_id, "жалоба клиента", idem=idem("susp-1"))

    assert await _profile_status(provider.organization_id) == "suspended"
    profile = await providers.get_own_profile(scope_of(provider.admin))
    assert profile.accepting_new_requests is False
    with pytest.raises(NotFound):
        await providers.get_public_profile(provider.organization_id)

    async with db_session.transaction() as s:
        notifications = list(
            (
                await s.execute(
                    select(Notification).where(
                        Notification.notification_type == "provider.suspended"
                    )
                )
            ).scalars()
        )
    assert [n.recipient_user_id for n in notifications] == [customer.manager.user_id]

    await trust.reinstate_provider(
        operator, organization_id, "жалоба не подтвердилась", idem=idem("susp-2")
    )
    assert await _profile_status(provider.organization_id) == "active"


async def test_expired_verification_stops_counting_and_worker_reopens_it() -> None:
    """verification_cases.expires_at: признак снимается сразу по истечении срока,
    цикл worker возвращает проверку в очередь, а профиль — в needs_information."""
    provider = await _submitted_provider("ver-exp")
    operator = await make_operator("op-exp")
    cases = await _cases(provider.organization_id)
    expires = utcnow() + timedelta(hours=1)
    for kind in ("requisites", "representative"):
        await trust.decide_verification_case(
            operator,
            ids.encode("verification_case", cases[kind].id),
            trust.VerificationDecisionData(
                decision="approved", reason="ЕГРЮЛ", source="ЕГРЮЛ", expires_at=expires
            ),
            idem=idem(f"ver-exp-{kind}"),
        )
    assert await _profile_status(provider.organization_id) == "active"
    async with db_session.transaction() as s:
        badges = await trust.verification_badges(s, provider.organization_id)
    assert all(b.confirmed for b in badges)

    later = utcnow() + timedelta(hours=2)
    set_clock(lambda: later)
    try:
        async with db_session.transaction() as s:
            badges = await trust.verification_badges(s, provider.organization_id)
            checks = await trust.active_checks(s, [provider.organization_id])
        assert not any(b.confirmed for b in badges)
        assert checks[provider.organization_id] == set()

        assert await trust.expire_verifications(later) == 2
        assert await trust.expire_verifications(later) == 0
    finally:
        set_clock(None)

    assert await _profile_status(provider.organization_id) == "needs_information"
    async with db_session.transaction() as s:
        org = await s.get(Organization, provider.organization_id)
        assert org is not None
        assert org.details_verification_status == "pending"
        assert org.representative_verification_status == "pending"
        rows = list(
            (
                await s.execute(
                    select(VerificationCase).where(
                        VerificationCase.organization_id == provider.organization_id
                    )
                )
            ).scalars()
        )
    decisions = sorted((row.check_kind, row.decision) for row in rows)
    assert decisions == [
        ("representative", "pending"),
        ("representative", "revoked"),
        ("requisites", "pending"),
        ("requisites", "revoked"),
    ]
    assert all(row.supersedes_case_id for row in rows if row.decision == "pending")


async def test_decision_rejects_expiry_in_the_past() -> None:
    provider = await _submitted_provider("ver-past")
    operator = await make_operator("op-past")
    case = (await _cases(provider.organization_id))["requisites"]
    with pytest.raises(ValidationFailed):
        await trust.decide_verification_case(
            operator,
            ids.encode("verification_case", case.id),
            trust.VerificationDecisionData(
                decision="approved",
                reason="ЕГРЮЛ",
                source="ЕГРЮЛ",
                expires_at=utcnow() - timedelta(minutes=1),
            ),
            idem=idem("ver-past-1"),
        )


async def _approved_case(organization_id, kind: str, *, checked_at, expires_at):  # type: ignore[no-untyped-def]
    async with db_session.transaction() as s:
        case = VerificationCase(
            organization_id=organization_id,
            subject_type=kind,
            check_kind=kind,
            decision="approved",
            decision_reason="ЕГРЮЛ",
            source="ЕГРЮЛ",
            checked_at=checked_at,
            expires_at=expires_at,
        )
        s.add(case)
        org = await s.get(Organization, organization_id)
        assert org is not None
        org.is_customer = True
        org.representative_verification_status = "verified"
        org.representative_verified_at = checked_at
        await s.flush()
        return case.id


async def test_representative_status_survives_while_other_side_check_is_valid() -> None:
    """Представитель заказчика и исполнителя ведут один статус: истечение одного
    вида не снимает признак, пока действует дело другого вида."""
    provider = await make_provider("ver-both", verified=True)
    now = utcnow()
    await _approved_case(
        provider.organization_id,
        "customer_representative",
        checked_at=now - timedelta(days=2),
        expires_at=now + timedelta(hours=5),
    )
    await _approved_case(
        provider.organization_id,
        "representative",
        checked_at=now - timedelta(days=1),
        expires_at=now + timedelta(hours=1),
    )

    later = now + timedelta(hours=2)
    set_clock(lambda: later)
    try:
        async with db_session.transaction() as s:
            checks = await trust.active_checks(s, [provider.organization_id])
        assert "representative" in checks[provider.organization_id]

        assert await trust.expire_verifications(later) == 1
    finally:
        set_clock(None)

    async with db_session.transaction() as s:
        org = await s.get(Organization, provider.organization_id)
        assert org is not None
        assert org.representative_verification_status == "verified"


async def test_failing_case_does_not_block_expiry_of_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.trust import verification

    verification.reset_expiry_quarantine()
    first = await make_provider("ver-bad", inn=None)
    second = await make_provider("ver-good", inn=None)
    now = utcnow()
    bad = await _approved_case(
        first.organization_id,
        "representative",
        checked_at=now - timedelta(days=1),
        expires_at=now - timedelta(hours=2),
    )
    good = await _approved_case(
        second.organization_id,
        "representative",
        checked_at=now - timedelta(days=1),
        expires_at=now - timedelta(hours=1),
    )
    original = verification._expire_case
    attempts: list[object] = []

    async def flaky(ctx, case):  # type: ignore[no-untyped-def]
        if case.id == bad:
            attempts.append(case.id)
            raise RuntimeError("сбой записи")
        await original(ctx, case)

    monkeypatch.setattr(verification, "_expire_case", flaky)
    try:
        assert await trust.expire_verifications(now) == 1
        assert await trust.expire_verifications(now) == 0
    finally:
        verification.reset_expiry_quarantine()
    assert attempts == [bad]

    async with db_session.transaction() as s:
        good_case = await s.get(VerificationCase, good)
        bad_case = await s.get(VerificationCase, bad)
        assert good_case is not None and good_case.decision == "revoked"
        assert bad_case is not None and bad_case.decision == "approved"
