import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import asyncpg as postgresql_asyncpg

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound, RateLimited, ValidationFailed
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import (
    AuditEntry,
    Equipment,
    IntegrationEvent,
    Organization,
    ServiceBinding,
    ServiceContract,
)
from app.infra.config import get_settings
from app.modules.identity import api as identity
from app.modules.trust import api as trust
from tests import factories
from tests.support import (
    CUSTOMER_INN,
    OTHER_INN,
    CustomerFixture,
    ProviderFixture,
    actor_of,
    add_equipment,
    idem,
    make_customer,
    make_operator,
    make_provider,
)

pytestmark = pytest.mark.usefixtures("clean_db")


async def _pair(
    key: str, *, customer_verified: bool = True
) -> tuple[ProviderFixture, CustomerFixture]:
    provider = await make_provider(f"{key}-p", status="active", accepting=True, verified=True)
    customer = await make_customer(f"{key}-c", verified=customer_verified)
    return provider, customer


def _equipment_id(customer: CustomerFixture) -> str:
    return ids.encode("equipment", customer.equipment_id)


def _one(customer: CustomerFixture) -> list[trust.BindingItemMatch]:
    return [trust.BindingItemMatch(item_index=0, equipment_id=_equipment_id(customer))]


async def _invite(
    provider: ProviderFixture,
    key: str,
    *,
    number: str = "Д-100",
    basis: str = "service_contract",
    customer_inn: str = CUSTOMER_INN,
    descriptions: list[str] | None = None,
) -> tuple[str, str]:
    result = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=customer_inn,
            contract_number=number,
            basis=basis,
            equipment_descriptions=descriptions or ["Холодильная витрина"],
        ),
        idem=idem(key),
    )
    return result.body["token"], result.body["id"]


async def test_invitation_accept_creates_confirmed_binding() -> None:
    provider, customer = await _pair("inv-ok")
    token, invitation_id = await _invite(provider, "inv-ok-1")

    preview = await trust.preview_binding_invitation(token, customer.manager)
    assert preview.provider_name == "ООО Сервис"
    assert preview.contract_number == "Д-100"
    assert preview.equipment_descriptions == ["Холодильная витрина"]
    assert preview.state == "active"

    result = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("inv-ok-2")
    )
    assert result.status == 201
    binding = result.body["items"][0]
    assert binding["status"] == "confirmed"
    assert binding["status_explanation"] == "Обслуживание подтверждено компанией"
    assert binding["contract_number"] == "Д-100"
    assert binding["provider"]["name"] == "ООО Сервис"

    async with db_session.transaction() as s:
        events = list(
            (
                await s.execute(
                    select(IntegrationEvent).where(
                        IntegrationEvent.event_type == "service_binding.changed"
                    )
                )
            ).scalars()
        )
    assert len(events) == 1
    assert events[0].recipient_org_id == provider.organization_id
    assert "token" not in json.dumps(events[0].payload)

    with pytest.raises(Conflict):
        await trust.accept_binding_invitation(
            customer.manager, token, _one(customer), idem=idem("inv-ok-3")
        )

    items, _ = await trust.list_binding_invitations(scope_of(provider.admin))
    assert [i.id for i in items] == [invitation_id]
    assert items[0].state == "used"
    assert not hasattr(items[0], "token")


async def test_invitation_waits_for_customer_verification() -> None:
    provider, customer = await _pair("inv-wait", customer_verified=False)
    token, _ = await _invite(provider, "inv-wait-1")
    result = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("inv-wait-2")
    )
    binding_id = result.body["items"][0]["id"]
    assert result.body["items"][0]["status"] == "pending"

    operator = await make_operator("op-inv-wait")
    async with db_session.transaction() as s:
        org = await s.get(Organization, customer.organization_id)
        assert org is not None
        case = await factories.create_verification_case(
            s,
            org,
            check_kind="customer_representative",
            subject_type="customer_representative",
        )
        case_id = case.id

    await trust.decide_verification_case(
        operator,
        ids.encode("verification_case", case_id),
        trust.VerificationDecisionData(
            decision="approved", reason="контакт из договора", source="договор"
        ),
        idem=idem("inv-wait-3"),
    )
    view = await trust.get_binding(
        scope_of(customer.manager), ids.decode("service_binding", binding_id)
    )
    assert view.status == "confirmed"


async def test_invitation_only_for_active_provider_and_manager() -> None:
    draft = await make_provider("inv-draft", verified=True, inn=None)
    with pytest.raises(Conflict) as exc:
        await _invite(draft, "inv-draft-1")
    assert exc.value.code == "PROVIDER_NOT_ACTIVE"

    provider, customer = await _pair("inv-role")
    token, _ = await _invite(provider, "inv-role-1")
    with pytest.raises(Forbidden):
        await trust.accept_binding_invitation(customer.employee, token, [], idem=idem("inv-role-2"))
    with pytest.raises(Forbidden):
        await trust.accept_binding_invitation(provider.admin, token, [], idem=idem("inv-role-3"))


async def test_foreign_recipient_cannot_accept_and_token_survives() -> None:
    provider, customer = await _pair("inv-fwd")
    stranger = await make_customer("inv-fwd-x", inn=OTHER_INN)
    token, _ = await _invite(provider, "inv-fwd-1")

    with pytest.raises(Conflict):
        await trust.accept_binding_invitation(stranger.manager, token, [], idem=idem("inv-fwd-2"))

    result = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("inv-fwd-3")
    )
    assert result.body["items"][0]["status"] == "confirmed"


async def test_token_types_are_not_interchangeable() -> None:
    provider, customer = await _pair("inv-type")
    binding_token, _ = await _invite(provider, "inv-type-1")
    async with db_session.transaction() as s:
        org = await s.get(Organization, customer.organization_id)
        assert org is not None
        _invitation, staff_token = await factories.create_invitation(s, org)

    with pytest.raises(NotFound):
        await identity.preview_invitation(binding_token)
    with pytest.raises(Conflict):
        await identity.accept_invitation(customer.manager, binding_token, idem=idem("inv-type-2"))

    with pytest.raises(NotFound):
        await trust.preview_binding_invitation(staff_token)
    with pytest.raises(Conflict):
        await trust.accept_binding_invitation(
            customer.manager, staff_token, [], idem=idem("inv-type-3")
        )


async def test_preview_details_only_for_addressee_manager_while_pending() -> None:
    provider, customer = await _pair("inv-pv")
    stranger = await make_customer("inv-pv-x", inn=OTHER_INN, verified=True)
    issued = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=CUSTOMER_INN,
            contract_number="Д-900",
            equipment_items=[
                trust.BindingInvitationItem(description="Витрина", serial_number="SN-9")
            ],
        ),
        idem=idem("inv-pv-1"),
    )
    token = issued.body["token"]

    hidden = {
        "contract_number": None,
        "basis": None,
        "equipment_descriptions": [],
        "equipment_items": [],
        "equipment_ids": [],
        "valid_from": None,
        "valid_until": None,
        "expires_at": None,
        "details_disclosed": False,
    }
    for actor in (None, stranger.manager, customer.employee, provider.admin):
        preview = await trust.preview_binding_invitation(token, actor)
        assert preview.provider_name == "ООО Сервис"
        assert preview.state == "active"
        assert preview.requisites_verified is True
        assert preview.model_dump(include=set(hidden)) == hidden

    own = await trust.preview_binding_invitation(token, customer.manager)
    assert own.details_disclosed is True
    assert own.contract_number == "Д-900"
    assert [i.serial_number for i in own.equipment_items] == ["SN-9"]

    await trust.revoke_binding_invitation(provider.admin, issued.body["id"], idem=idem("inv-pv-2"))
    revoked = await trust.preview_binding_invitation(token, customer.manager)
    assert revoked.state == "revoked"
    assert revoked.model_dump(include=set(hidden)) == hidden


async def test_revoked_invitation_does_not_work() -> None:
    provider, customer = await _pair("inv-rev")
    token, invitation_id = await _invite(provider, "inv-rev-1")
    await trust.revoke_binding_invitation(provider.admin, invitation_id, idem=idem("inv-rev-2"))

    preview = await trust.preview_binding_invitation(token)
    assert preview.state == "revoked"
    with pytest.raises(Conflict):
        await trust.accept_binding_invitation(
            customer.manager, token, _one(customer), idem=idem("inv-rev-3")
        )


async def test_concurrent_accept_consumes_token_once() -> None:
    provider, customer = await _pair("inv-race")
    token, _ = await _invite(provider, "inv-race-1")
    equipment = _one(customer)

    outcomes = await asyncio.gather(
        trust.accept_binding_invitation(customer.manager, token, equipment, idem=idem("race-a")),
        trust.accept_binding_invitation(customer.manager, token, equipment, idem=idem("race-b")),
        return_exceptions=True,
    )
    succeeded = [o for o in outcomes if not isinstance(o, BaseException)]
    failed = [o for o in outcomes if isinstance(o, Conflict)]
    assert len(succeeded) == 1
    assert len(failed) == 1

    async with db_session.transaction() as s:
        bindings = list((await s.execute(select(ServiceBinding))).scalars())
    assert len(bindings) == 1


async def test_binding_request_answer_is_identical_for_unknown_contract() -> None:
    provider, customer = await _pair("req-neutral")
    async with db_session.transaction() as s:
        provider_org = await s.get(Organization, provider.organization_id)
        customer_org = await s.get(Organization, customer.organization_id)
        assert provider_org is not None and customer_org is not None
        await factories.create_service_contract(s, provider_org, customer_org, number="Д-777")

    second_equipment = await add_equipment(customer)
    provider_id = ids.encode("organization", provider.organization_id)

    existing = await trust.request_binding(
        customer.manager,
        trust.BindingRequestData(
            provider_organization_id=provider_id,
            contract_number="Д-777",
            equipment_ids=[_equipment_id(customer)],
        ),
        idem=idem("req-n1"),
    )
    missing = await trust.request_binding(
        customer.manager,
        trust.BindingRequestData(
            provider_organization_id=provider_id,
            contract_number="НЕТ-ТАКОГО",
            equipment_ids=[ids.encode("equipment", second_equipment)],
        ),
        idem=idem("req-n2"),
    )
    assert existing.status == missing.status == 202
    assert (existing.body["remaining_attempts"], missing.body["remaining_attempts"]) == (4, 3)
    existing_body = {k: v for k, v in existing.body.items() if k != "remaining_attempts"}
    missing_body = {k: v for k, v in missing.body.items() if k != "remaining_attempts"}
    assert json.dumps(existing_body, sort_keys=True) == json.dumps(missing_body, sort_keys=True)
    assert existing_body == {"status": "submitted", "message": "Запрос отправлен на проверку"}

    async with db_session.transaction() as s:
        statuses = [row.status for row in (await s.execute(select(ServiceBinding))).scalars()]
    assert statuses == ["pending", "pending"]


async def test_binding_request_does_not_reveal_foreign_data() -> None:
    provider, customer = await _pair("req-secret")
    other = await make_customer("req-secret-o", inn=OTHER_INN)
    provider_id = ids.encode("organization", provider.organization_id)

    with pytest.raises(NotFound):
        await trust.request_binding(
            customer.manager,
            trust.BindingRequestData(
                provider_organization_id=provider_id,
                contract_number="Д-1",
                equipment_ids=[ids.encode("equipment", other.equipment_id)],
            ),
            idem=idem("req-s1"),
        )

    await trust.request_binding(
        customer.manager,
        trust.BindingRequestData(
            provider_organization_id=provider_id,
            contract_number="Д-1",
            equipment_ids=[_equipment_id(customer)],
        ),
        idem=idem("req-s2"),
    )
    items, _ = await trust.list_bindings(scope_of(provider.dispatcher))
    assert len(items) == 1
    assert items[0].contract_number == "Д-1"
    assert items[0].status == "pending"
    assert not hasattr(items[0], "warranty_authorization")


async def test_provider_confirms_or_rejects_request() -> None:
    provider, customer = await _pair("req-resp")
    provider_id = ids.encode("organization", provider.organization_id)
    await trust.request_binding(
        customer.manager,
        trust.BindingRequestData(
            provider_organization_id=provider_id,
            contract_number="Д-5",
            equipment_ids=[_equipment_id(customer)],
        ),
        idem=idem("req-resp-1"),
    )
    items, _ = await trust.list_bindings(scope_of(provider.dispatcher))
    binding_id = items[0].id

    with pytest.raises(ValidationFailed):
        await trust.respond_binding(
            provider.dispatcher, binding_id, "reject", None, idem=idem("req-resp-2")
        )

    result = await trust.respond_binding(
        provider.dispatcher, binding_id, "confirm", None, idem=idem("req-resp-3")
    )
    assert result.body["status"] == "confirmed"

    equipment, _ = await trust.list_provider_equipment(scope_of(provider.admin))
    assert equipment == [customer.equipment_id]


async def test_foreign_provider_cannot_touch_binding() -> None:
    provider, customer = await _pair("req-foreign")
    stranger = await make_provider(
        "req-foreign-x", status="active", accepting=True, verified=False, inn=None
    )
    await trust.request_binding(
        customer.manager,
        trust.BindingRequestData(
            provider_organization_id=ids.encode("organization", provider.organization_id),
            contract_number="Д-9",
            equipment_ids=[_equipment_id(customer)],
        ),
        idem=idem("req-f1"),
    )
    items, _ = await trust.list_bindings(scope_of(provider.dispatcher))
    binding_id = items[0].id

    with pytest.raises(NotFound):
        await trust.respond_binding(
            stranger.dispatcher, binding_id, "confirm", None, idem=idem("req-f2")
        )
    foreign_items, _ = await trust.list_bindings(scope_of(stranger.admin))
    assert foreign_items == []
    with pytest.raises(NotFound):
        await trust.get_binding(scope_of(stranger.admin), ids.decode("service_binding", binding_id))


async def test_binding_request_rate_limit() -> None:
    provider, customer = await _pair("req-rate")
    provider_id = ids.encode("organization", provider.organization_id)
    equipment_id = _equipment_id(customer)

    for attempt in range(5):
        await trust.request_binding(
            customer.manager,
            trust.BindingRequestData(
                provider_organization_id=provider_id,
                contract_number=f"Д-{attempt}",
                equipment_ids=[equipment_id],
            ),
            idem=idem(f"req-rate-{attempt}"),
        )

    with pytest.raises(RateLimited):
        await trust.request_binding(
            customer.manager,
            trust.BindingRequestData(
                provider_organization_id=provider_id,
                contract_number="Д-6",
                equipment_ids=[equipment_id],
            ),
            idem=idem("req-rate-6"),
        )

    async with db_session.transaction() as s:
        rejected = list(
            (
                await s.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "service_binding.request_rejected"
                    )
                )
            ).scalars()
        )
    assert len(rejected) == 1
    assert rejected[0].result == "denied"


async def test_personal_contact_is_never_confirmed() -> None:
    customer = await make_customer("contact")
    result = await trust.create_contact_binding(
        customer.manager,
        trust.ContactBindingData(
            equipment_id=_equipment_id(customer), contact_name="Мастер Пётр", contact_phone="+7900"
        ),
        idem=idem("contact-1"),
    )
    body = result.body
    assert body["is_contact_only"] is True
    assert body["provider"]["organization_id"] is None
    assert body["provider"]["is_platform_member"] is False
    assert body["status"] != "confirmed"
    assert "не доставляет обращения" in body["status_explanation"]


async def test_either_side_revokes_binding() -> None:
    provider, customer = await _pair("rev")
    token, _ = await _invite(provider, "rev-1")
    accepted = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("rev-2")
    )
    binding_id = accepted.body["items"][0]["id"]

    with pytest.raises(ValidationFailed):
        await trust.revoke_binding(customer.manager, binding_id, "  ", idem=idem("rev-3"))

    result = await trust.revoke_binding(
        provider.admin, binding_id, "договор расторгнут", idem=idem("rev-4")
    )
    assert result.body["status"] == "revoked"
    assert result.body["status_reason"] == "договор расторгнут"
    with pytest.raises(Conflict):
        await trust.revoke_binding(customer.manager, binding_id, "повторно", idem=idem("rev-5"))


async def test_contract_number_is_claimed_by_first_acceptance() -> None:
    provider = await make_provider("ctr-x", status="active", accepting=True, verified=True)
    first = await make_customer("ctr-x-1")
    second = await make_customer("ctr-x-2", inn=OTHER_INN, verified=True)

    token1, _ = await _invite(provider, "ctr-x-1", number="Д-42")
    await trust.accept_binding_invitation(first.manager, token1, _one(first), idem=idem("ctr-x-2"))

    token2, _ = await _invite(provider, "ctr-x-3", customer_inn=OTHER_INN, number="Д-42")
    with pytest.raises(Conflict) as exc:
        await trust.accept_binding_invitation(
            second.manager, token2, _one(second), idem=idem("ctr-x-4")
        )
    assert exc.value.code == "CONTRACT_NUMBER_TAKEN"

    async with db_session.transaction() as s:
        contracts = list((await s.execute(select(ServiceContract))).scalars())
    assert len(contracts) == 1


async def test_client_registers_after_receiving_invitation() -> None:
    provider = await make_provider("inv-new", status="active", accepting=True, verified=True)
    issued = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=OTHER_INN,
            contract_number="Д-200",
            customer_name="Новый Заказчик",
            equipment_descriptions=["Витрина холодильная"],
        ),
        idem=idem("inv-new-1"),
    )
    token = issued.body["token"]
    assert issued.body["customer_organization_id"] is None

    preview = await trust.preview_binding_invitation(token)
    assert preview.contract_number is None
    assert preview.state == "active"

    customer = await make_customer("inv-new-c", inn=OTHER_INN, verified=True)
    preview = await trust.preview_binding_invitation(token, customer.manager)
    assert preview.contract_number == "Д-200"

    result = await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("inv-new-2")
    )
    binding = result.body["items"][0]
    assert binding["status"] == "confirmed"
    assert binding["contract_number"] == "Д-200"

    async with db_session.transaction() as s:
        contracts = list((await s.execute(select(ServiceContract))).scalars())
    assert len(contracts) == 1
    assert contracts[0].customer_org_id == customer.organization_id

    items, _ = await trust.list_binding_invitations(scope_of(provider.admin))
    assert items[0].customer_organization_id == ids.encode("organization", customer.organization_id)


async def test_accept_with_mismatched_inn_is_refused_and_token_survives() -> None:
    provider = await make_provider("inv-mismatch", status="active", accepting=True, verified=True)
    customer = await make_customer("inv-mismatch-c", verified=True)
    token, _ = await _invite(provider, "inv-mismatch-1", customer_inn=OTHER_INN, number="Д-202")

    with pytest.raises(Conflict) as exc:
        await trust.accept_binding_invitation(
            customer.manager, token, _one(customer), idem=idem("inv-mismatch-2")
        )
    assert exc.value.code == "INVITATION_INVALID"
    assert exc.value.details == {}

    owner = await make_customer("inv-mismatch-o", inn=OTHER_INN, verified=True)
    result = await trust.accept_binding_invitation(
        owner.manager, token, _one(owner), idem=idem("inv-mismatch-3")
    )
    assert result.body["items"][0]["status"] == "confirmed"


async def test_customer_employee_sees_only_own_locations() -> None:
    provider, customer = await _pair("scope-emp")
    token, _ = await _invite(provider, "scope-emp-1")
    await trust.accept_binding_invitation(
        customer.manager, token, _one(customer), idem=idem("scope-emp-2")
    )

    items, _ = await trust.list_bindings(scope_of(customer.employee))
    assert [item.id for item in items] == [
        item.id for item in (await trust.list_bindings(scope_of(customer.manager)))[0]
    ]


async def _set_serial(equipment_id: object, serial: str) -> None:
    async with db_session.transaction() as s:
        row = await s.get(Equipment, equipment_id)
        assert row is not None
        row.serial_number = serial


async def test_invitation_confirms_exactly_listed_equipment() -> None:
    provider, customer = await _pair("inv-items")
    second = await add_equipment(customer)
    extra = await add_equipment(customer)
    await _set_serial(customer.equipment_id, "SN-001")
    await _set_serial(second, "SN-002")
    issued = await trust.create_binding_invitation(
        provider.admin,
        trust.BindingInvitationData(
            customer_inn=CUSTOMER_INN,
            contract_number="Д-300",
            equipment_items=[
                trust.BindingInvitationItem(description="Витрина", serial_number="SN-001"),
                trust.BindingInvitationItem(description="Ларь", serial_number="sn 002", model="L2"),
            ],
        ),
        idem=idem("inv-items-1"),
    )
    token = issued.body["token"]
    assert [i["serial_number"] for i in issued.body["equipment_items"]] == ["SN-001", "sn 002"]
    preview = await trust.preview_binding_invitation(token, customer.manager)
    assert [i.description for i in preview.equipment_items] == ["Витрина", "Ларь"]

    first_id = _equipment_id(customer)
    second_id = ids.encode("equipment", second)
    with pytest.raises(ValidationFailed):
        await trust.accept_binding_invitation(
            customer.manager,
            token,
            [trust.BindingItemMatch(item_index=0, equipment_id=first_id)],
            idem=idem("inv-items-2"),
        )
    with pytest.raises(ValidationFailed) as exc:
        await trust.accept_binding_invitation(
            customer.manager,
            token,
            [
                trust.BindingItemMatch(item_index=0, equipment_id=second_id),
                trust.BindingItemMatch(item_index=1, equipment_id=first_id),
            ],
            idem=idem("inv-items-3"),
        )
    assert exc.value.code == "SERIAL_NUMBER_MISMATCH"

    result = await trust.accept_binding_invitation(
        customer.manager,
        token,
        [
            trust.BindingItemMatch(item_index=1, equipment_id=second_id),
            trust.BindingItemMatch(item_index=0, equipment_id=first_id),
        ],
        idem=idem("inv-items-4"),
    )
    items = result.body["items"]
    assert [(i["equipment_id"], i["invitation_item_index"]) for i in items] == [
        (first_id, 0),
        (second_id, 1),
    ]
    async with db_session.transaction() as s:
        bound = {row.equipment_id for row in (await s.execute(select(ServiceBinding))).scalars()}
    assert bound == {customer.equipment_id, second}
    assert extra not in bound


async def test_invitation_requires_equipment_list() -> None:
    provider, _ = await _pair("inv-empty")
    with pytest.raises(ValidationFailed) as exc:
        await trust.create_binding_invitation(
            provider.admin,
            trust.BindingInvitationData(customer_inn=CUSTOMER_INN, contract_number="Д-1"),
            idem=idem("inv-empty-1"),
        )
    assert exc.value.details["field"] == "equipment_items"


async def test_invitation_is_not_captured_by_unverified_namesake() -> None:
    provider = await make_provider("inv-squat", status="active", accepting=True, verified=True)
    squatter = await make_customer("inv-squat-s", verified=False)
    owner = await make_customer("inv-squat-o", verified=True)
    token, _ = await _invite(provider, "inv-squat-1")

    with pytest.raises(Conflict) as exc:
        await trust.accept_binding_invitation(
            squatter.manager, token, _one(squatter), idem=idem("inv-squat-2")
        )
    assert exc.value.code == "INVITATION_INVALID"
    result = await trust.accept_binding_invitation(
        owner.manager, token, _one(owner), idem=idem("inv-squat-3")
    )
    assert result.body["items"][0]["status"] == "confirmed"


async def test_verified_owner_registered_after_issue_wins_over_namesake() -> None:
    provider = await make_provider("inv-late", status="active", accepting=True, verified=True)
    token, _ = await _invite(provider, "inv-late-1")
    squatter = await make_customer("inv-late-s", verified=False)
    owner = await make_customer("inv-late-o", verified=True)

    with pytest.raises(Conflict):
        await trust.accept_binding_invitation(
            squatter.manager, token, _one(squatter), idem=idem("inv-late-2")
        )
    result = await trust.accept_binding_invitation(
        owner.manager, token, _one(owner), idem=idem("inv-late-3")
    )
    assert result.body["items"][0]["status"] == "confirmed"


def _request(provider: ProviderFixture, customer: CustomerFixture, number: str):
    return trust.BindingRequestData(
        provider_organization_id=ids.encode("organization", provider.organization_id),
        contract_number=number,
        equipment_ids=[_equipment_id(customer)],
    )


async def test_binding_request_limit_is_per_pair_not_per_provider() -> None:
    provider, attacker = await _pair("req-pair")
    victim = await make_customer("req-pair-v", inn=OTHER_INN)
    for attempt in range(5):
        await trust.request_binding(
            attacker.manager,
            _request(provider, attacker, f"Д-{attempt}"),
            idem=idem(f"rp-{attempt}"),
        )
    with pytest.raises(RateLimited):
        await trust.request_binding(
            attacker.manager, _request(provider, attacker, "Д-6"), idem=idem("rp-6")
        )

    result = await trust.request_binding(
        victim.manager, _request(provider, victim, "Д-1"), idem=idem("rp-victim")
    )
    assert result.status == 202

    async with db_session.transaction() as s:
        org = await s.get(Organization, attacker.organization_id)
        assert org is not None
        colleague = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="req-pair-mgr2"), org
        )
    with pytest.raises(RateLimited):
        await trust.request_binding(
            actor_of(colleague), _request(provider, attacker, "Д-7"), idem=idem("rp-colleague")
        )

    async with db_session.transaction() as s:
        rejected = list(
            (
                await s.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "service_binding.request_rejected"
                    )
                )
            ).scalars()
        )
    assert sorted(r.details["scope"] for r in rejected) == ["organization", "user"]


async def test_binding_request_provider_wide_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINDING_REQUEST_PROVIDER_LIMIT", "2")
    get_settings.cache_clear()
    provider, first = await _pair("req-wide")
    second = await make_customer("req-wide-2", inn=OTHER_INN)
    third = await make_customer("req-wide-3", inn=OTHER_INN)
    await trust.request_binding(first.manager, _request(provider, first, "Д-1"), idem=idem("rw-1"))
    await trust.request_binding(
        second.manager, _request(provider, second, "Д-2"), idem=idem("rw-2")
    )
    with pytest.raises(RateLimited):
        await trust.request_binding(
            third.manager, _request(provider, third, "Д-3"), idem=idem("rw-3")
        )
    async with db_session.transaction() as s:
        rejected = list(
            (
                await s.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "service_binding.request_rejected"
                    )
                )
            ).scalars()
        )
    assert [r.details["scope"] for r in rejected] == ["provider"]


async def test_concurrent_binding_requests_do_not_overshoot_limit() -> None:
    provider, customer = await _pair("req-race")
    outcomes = await asyncio.gather(
        *(
            trust.request_binding(
                customer.manager, _request(provider, customer, f"Д-{i}"), idem=idem(f"rr-{i}")
            )
            for i in range(8)
        ),
        return_exceptions=True,
    )
    succeeded = [o for o in outcomes if not isinstance(o, BaseException)]
    limited = [o for o in outcomes if isinstance(o, RateLimited)]
    assert len(succeeded) == 5
    assert len(limited) == 3


async def test_serial_number_hidden_after_rejection() -> None:
    provider, customer = await _pair("serial-hide")
    await _set_serial(customer.equipment_id, "SN-SECRET")
    await trust.request_binding(
        customer.manager, _request(provider, customer, "Д-1"), idem=idem("sh-1")
    )
    items, _ = await trust.list_bindings(scope_of(provider.dispatcher))
    assert items[0].equipment is not None
    assert items[0].equipment.serial_number == "SN-SECRET"

    rejected = await trust.respond_binding(
        provider.dispatcher, items[0].id, "reject", "не наш клиент", idem=idem("sh-2")
    )
    assert rejected.body["equipment"]["serial_number"] is None
    items, _ = await trust.list_bindings(scope_of(provider.dispatcher))
    assert items[0].equipment is not None
    assert items[0].equipment.serial_number is None


async def test_request_rate_query_uses_expression_index() -> None:
    from app.modules.trust.bindings import request_attempts

    stmt = request_attempts(uuid.uuid4(), utcnow() - timedelta(minutes=15))
    compiled = stmt.compile(dialect=postgresql_asyncpg.dialect())
    args = ", ".join(
        "now()" if name.startswith("occurred_at") else "'x'" for name in compiled.positiontup or []
    )
    async with db_session.transaction() as s:
        await s.execute(select(1))
        connection = await s.connection()
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        assert driver is not None
        await driver.execute("SET LOCAL plan_cache_mode = force_generic_plan")
        await driver.execute("SET LOCAL enable_seqscan = off")
        await driver.execute(f"PREPARE binding_rate AS {compiled}")
        rows = await driver.fetch(f"EXPLAIN EXECUTE binding_rate({args})")
        await driver.execute("DEALLOCATE binding_rate")
    plan = "\n".join(row[0] for row in rows)
    assert "ix_audit_entries_binding_request" in plan, plan
