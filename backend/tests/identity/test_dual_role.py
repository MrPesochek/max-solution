import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.core import ids
from app.core.actor import BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Membership, Organization, ProviderProfile
from app.modules.identity import api as identity
from app.modules.requests import api as requests_api
from app.modules.trust import api as trust
from tests import factories
from tests.requests import factories as req_factories
from tests.requests import helpers as h

pytestmark = pytest.mark.usefixtures("clean_db")

VALID_INN = "7707083893"


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="dual", body_hash=hash_body({"k": key}))


def _actor(membership: Membership) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


def _session_info(user_id: uuid.UUID) -> identity.SessionInfo:
    return identity.SessionInfo(
        session_id=uuid.uuid4(),
        user_id=user_id,
        display_name="Тест",
        expires_at=utcnow() + timedelta(hours=1),
    )


def _profile_of(organization_id: uuid.UUID) -> Select[tuple[ProviderProfile]]:
    return select(ProviderProfile).where(ProviderProfile.organization_id == organization_id)


async def _customer_manager(
    max_user_id: str = "dual-mgr", *, inn: str | None = None
) -> tuple[Organization, Membership]:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, inn=inn)
        user = await factories.create_user(s, max_user_id=max_user_id)
        membership = await factories.create_membership(s, user, org)
        return org, membership


async def _dual() -> tuple[Organization, Membership, Membership]:
    org, customer = await _customer_manager()
    result = await identity.add_participation(
        _actor(customer),
        org.id,
        identity.ParticipationData(kind="provider"),
        idem=_idem("dual-add"),
    )
    async with db_session.transaction() as s:
        provider = await s.get(
            Membership, ids.decode("membership", result.body["membership"]["id"])
        )
        assert provider is not None
    return org, customer, provider


async def test_customer_adds_provider_participation() -> None:
    org, customer = await _customer_manager()

    result = await identity.add_participation(
        _actor(customer),
        org.id,
        identity.ParticipationData(kind="provider"),
        idem=_idem("add-1"),
    )

    assert result.status == 201
    assert result.body["organization"]["kinds"] == ["customer", "provider"]
    membership = result.body["membership"]
    assert membership["role"] == "provider_admin"
    assert membership["side"] == "provider"
    assert membership["id"] != ids.encode("membership", customer.id)
    async with db_session.transaction() as s:
        profile = (await s.execute(_profile_of(org.id))).scalar_one()
    assert profile.status == "draft"
    assert profile.accepting_new_requests is False

    with pytest.raises(Conflict) as exc:
        await identity.add_participation(
            _actor(customer),
            org.id,
            identity.ParticipationData(kind="provider"),
            idem=_idem("add-2"),
        )
    assert exc.value.code == "PARTICIPATION_EXISTS"


async def test_add_participation_requires_manager_of_this_organization() -> None:
    org, _manager = await _customer_manager()
    other_org, other_manager = await _customer_manager("dual-other")
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id="dual-emp")
        employee = await factories.create_membership(s, user, org, role="customer_employee")

    with pytest.raises(Forbidden):
        await identity.add_participation(
            _actor(employee), org.id, identity.ParticipationData(kind="provider"), idem=None
        )
    with pytest.raises(NotFound):
        await identity.add_participation(
            _actor(other_manager), org.id, identity.ParticipationData(kind="provider"), idem=None
        )
    assert other_org.id != org.id


async def test_verified_inn_of_other_provider_blocks_provider_participation() -> None:
    async with db_session.transaction() as s:
        taken = await factories.create_organization(s, customer=False, provider=True, inn=VALID_INN)
        taken.details_verification_status = "verified"
    org, manager = await _customer_manager(inn=VALID_INN)
    async with db_session.transaction() as s:
        row = await s.get(Organization, org.id)
        assert row is not None
        row.details_verification_status = "verified"

    with pytest.raises(Conflict) as exc:
        await identity.add_participation(
            _actor(manager), org.id, identity.ParticipationData(kind="provider"), idem=None
        )
    assert exc.value.code == "INN_ALREADY_VERIFIED"
    async with db_session.transaction() as s:
        row = await s.get(Organization, org.id)
        assert row is not None and row.is_provider is False


async def test_one_membership_per_side() -> None:
    org, customer, _provider = await _dual()
    user_id = customer.user_id
    with pytest.raises(IntegrityError):
        async with db_session.transaction() as s:
            s.add(
                Membership(
                    user_id=user_id,
                    organization_id=org.id,
                    role="customer_employee",
                    status="active",
                )
            )
            await s.flush()
    with pytest.raises(IntegrityError):
        async with db_session.transaction() as s:
            s.add(
                Membership(
                    user_id=user_id,
                    organization_id=org.id,
                    role="provider_dispatcher",
                    status="active",
                )
            )
            await s.flush()


async def test_actor_is_resolved_by_membership_not_organization_kind() -> None:
    org, customer, provider = await _dual()
    info = _session_info(customer.user_id)
    org_pid = ids.encode("organization", org.id)

    with pytest.raises(Conflict) as exc:
        await identity.resolve_actor(info, org_pid)
    assert exc.value.code == "MEMBERSHIP_AMBIGUOUS"

    as_provider = await identity.resolve_actor(info, None, ids.encode("membership", provider.id))
    assert isinstance(as_provider, UserActor)
    assert as_provider.side == "provider"
    assert as_provider.organization_id == org.id

    as_customer = await identity.resolve_actor(info, org_pid, ids.encode("membership", customer.id))
    assert isinstance(as_customer, UserActor)
    assert as_customer.side == "customer"

    other_org, other = await _customer_manager("dual-foreign")
    with pytest.raises(NotFound):
        await identity.resolve_actor(info, None, ids.encode("membership", other.id))
    with pytest.raises(NotFound):
        await identity.resolve_actor(
            info, ids.encode("organization", other_org.id), ids.encode("membership", provider.id)
        )


async def test_staff_of_other_side_is_out_of_context() -> None:
    org, customer, provider = await _dual()
    async with db_session.transaction() as s:
        dispatcher_user = await factories.create_user(s, max_user_id="dual-disp")
        dispatcher = await factories.create_membership(
            s, dispatcher_user, org, role="provider_dispatcher", status="pending"
        )
        employee_user = await factories.create_user(s, max_user_id="dual-emp2")
        employee = await factories.create_membership(
            s, employee_user, org, role="customer_employee"
        )

    customer_members, _ = await identity.list_members(scope_of(_actor(customer)))
    provider_members, _ = await identity.list_members(scope_of(_actor(provider)))
    assert {m.id for m in customer_members} == {
        ids.encode("membership", customer.id),
        ids.encode("membership", employee.id),
    }
    assert {m.id for m in provider_members} == {
        ids.encode("membership", provider.id),
        ids.encode("membership", dispatcher.id),
    }
    assert {m.side for m in provider_members} == {"provider"}

    with pytest.raises(NotFound):
        await identity.revoke_membership(
            _actor(customer), ids.encode("membership", dispatcher.id), idem=None
        )
    with pytest.raises(NotFound):
        await identity.approve_membership(
            _actor(customer), ids.encode("membership", dispatcher.id), idem=None
        )
    with pytest.raises(NotFound):
        await identity.revoke_membership(
            _actor(provider), ids.encode("membership", employee.id), idem=None
        )
    approved = await identity.approve_membership(
        _actor(provider), ids.encode("membership", dispatcher.id), idem=None
    )
    assert approved.body["status"] == "active"


async def test_invitation_role_sets_side_of_new_membership() -> None:
    org, customer, provider = await _dual()
    issued = await identity.create_invitation(
        _actor(provider),
        identity.InvitationCreateData(role="provider_dispatcher"),
        idem=_idem("inv-disp"),
    )
    customer_invitations, _ = await identity.list_invitations(scope_of(_actor(customer)))
    assert customer_invitations == []

    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id="dual-invitee")
        await factories.create_membership(s, user, org, role="customer_employee")
        invitee_id = user.id
    accepted = await identity.accept_invitation(
        BareUserActor(invitee_id), issued.body["token"], idem=None
    )
    assert accepted.body["side"] == "provider"
    assert accepted.body["role"] == "provider_dispatcher"

    same_side = await identity.create_invitation(
        _actor(customer),
        identity.InvitationCreateData(role="customer_employee"),
        idem=_idem("inv-emp"),
    )
    with pytest.raises(Conflict) as exc:
        await identity.accept_invitation(
            BareUserActor(invitee_id), same_side.body["token"], idem=None
        )
    assert exc.value.code == "ALREADY_MEMBER"


async def test_update_organization_by_id_and_requisites_rules() -> None:
    org, customer, provider = await _dual()
    renamed = await identity.update_organization(
        _actor(provider),
        identity.OrganizationUpdateData(name="Новое имя", contact_name="Иван"),
        idem=_idem("upd-1"),
        organization_id=org.id,
    )
    assert renamed.body["name"] == "Новое имя"
    assert renamed.body["contact_name"] == "Иван"

    other_org, _ = await _customer_manager("dual-upd-other")
    with pytest.raises(NotFound):
        await identity.update_organization(
            _actor(customer),
            identity.OrganizationUpdateData(name="Чужое"),
            idem=None,
            organization_id=other_org.id,
        )

    async with db_session.transaction() as s:
        row = await s.get(Organization, org.id)
        assert row is not None
        row.inn_raw = row.inn_normalized = VALID_INN
        row.legal_form = "ooo"
        row.details_verification_status = "pending"
    with pytest.raises(Conflict) as exc:
        await identity.update_organization(
            _actor(customer), identity.OrganizationUpdateData(legal_form="ip"), idem=None
        )
    assert exc.value.code == "REQUISITES_UNDER_REVIEW"

    async with db_session.transaction() as s:
        row = await s.get(Organization, org.id)
        assert row is not None
        row.details_verification_status = "verified"
        profile = (await s.execute(_profile_of(org.id))).scalar_one()
        profile.status = "active"
    with pytest.raises(Conflict) as exc:
        await identity.update_organization(
            _actor(customer), identity.OrganizationUpdateData(inn="500100732259"), idem=None
        )
    assert exc.value.code == "INN_LOCKED"

    same = await identity.update_organization(
        _actor(customer),
        identity.OrganizationUpdateData(inn=VALID_INN, name="Ещё имя"),
        idem=None,
    )
    assert same.body["details_verification_status"] == "verified"

    changed = await identity.update_organization(
        _actor(customer), identity.OrganizationUpdateData(legal_form="ip"), idem=None
    )
    assert changed.body["details_verification_status"] == "unverified"
    async with db_session.transaction() as s:
        profile = (await s.execute(_profile_of(org.id))).scalar_one()
    assert profile.status == "needs_information"


async def test_organization_cannot_take_its_own_request() -> None:
    world = await req_factories.build_world()
    async with db_session.transaction() as s:
        customer = await s.get(Organization, world.customer_org_id)
        assert customer is not None
        customer.is_provider = True
        await req_factories.create_provider_profile(s, customer)
        await req_factories.create_provider_matching(
            s, customer, category_id=world.category_id, city_id=world.city_id
        )
        membership = await req_factories.create_membership(
            s, await req_factories.create_user(s, "Диспетчер себе"), customer, "provider_dispatcher"
        )
        self_dispatcher = _actor(membership)

    published = await h.make_published(world)
    assert published["search"]["matched_providers"] == 1

    cards, _ = await requests_api.list_marketplace_requests(self_dispatcher)
    assert cards == []
    with pytest.raises(NotFound):
        await requests_api.get_marketplace_card(self_dispatcher, h.rid(published))
    with pytest.raises(NotFound):
        await requests_api.submit_offer(
            self_dispatcher, h.rid(published), data=requests_api.OfferInput(amount_minor=1000)
        )


async def test_organization_cannot_bind_itself_as_own_service() -> None:
    world = await req_factories.build_world(binding_status=None)
    async with db_session.transaction() as s:
        customer = await s.get(Organization, world.customer_org_id)
        assert customer is not None
        customer.is_provider = True
        await req_factories.create_provider_profile(s, customer)

    with pytest.raises(Conflict) as exc:
        await trust.request_binding(
            world.manager,
            trust.BindingRequestData(
                provider_organization_id=ids.encode("organization", world.customer_org_id),
                contract_number="Д-1",
                equipment_ids=[ids.encode("equipment", world.equipment_id)],
            ),
            idem=None,
        )
    assert exc.value.code == "SELF_BINDING_FORBIDDEN"
