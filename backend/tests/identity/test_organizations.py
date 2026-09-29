import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Location, Membership, Organization, ProviderProfile
from app.modules.identity import api as identity
from app.modules.identity.inn import is_valid_inn, normalize_inn
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")

VALID_INN_10 = "7707083893"
VALID_INN_12 = "500100732259"


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="POST /organizations", body_hash=hash_body({"k": key}))


async def _bare_actor(max_user_id: str = "u1") -> BareUserActor:
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id=max_user_id)
        return BareUserActor(user.id)


def _customer_data(**kwargs: object) -> identity.OrganizationCreateData:
    base = {"name": "ООО Ромашка", "kind": "customer", "contact_phone": "+79990000000"}
    base.update(kwargs)
    return identity.OrganizationCreateData(**base)  # type: ignore[arg-type]


async def test_inn_checksums() -> None:
    assert is_valid_inn(VALID_INN_10)
    assert is_valid_inn(VALID_INN_12)
    assert not is_valid_inn("7707083894")
    assert not is_valid_inn("123")
    assert normalize_inn(" 770-708 3893 ") == VALID_INN_10


async def test_create_customer_organization_with_first_location() -> None:
    actor = await _bare_actor()
    async with db_session.transaction() as s:
        city = await factories.seed_city(s)
        city_id = city.id

    result = await identity.create_organization(
        actor,
        _customer_data(
            first_location=identity.FirstLocationData(
                name="Кафе на Ленина", city_id=city_id, address="ул. Ленина, 1"
            )
        ),
        idem=_idem("org-create-1"),
    )

    assert result.status == 201
    assert result.body["membership"]["role"] == "customer_manager"
    assert result.body["organization"]["kinds"] == ["customer"]

    async with db_session.transaction() as s:
        org = (await s.execute(select(Organization))).scalar_one()
        membership = (await s.execute(select(Membership))).scalar_one()
        location = (await s.execute(select(Location))).scalar_one()
    assert membership.status == "active"
    assert membership.organization_id == org.id
    assert location.customer_org_id == org.id


async def test_create_provider_organization_makes_draft_profile() -> None:
    actor = await _bare_actor("u-provider")
    result = await identity.create_organization(
        actor,
        identity.OrganizationCreateData(
            name="Сервис 24", kind="provider", contact_phone="+79990000001"
        ),
        idem=_idem("org-create-2"),
    )
    assert result.body["membership"]["role"] == "provider_admin"

    async with db_session.transaction() as s:
        profile = (await s.execute(select(ProviderProfile))).scalar_one()
    assert profile.status == "draft"


async def test_repeat_with_same_idempotency_key_creates_one_organization() -> None:
    actor = await _bare_actor("u-idem")
    idem = _idem("org-create-3")
    first = await identity.create_organization(actor, _customer_data(), idem=idem)
    second = await identity.create_organization(actor, _customer_data(), idem=idem)

    assert second.replayed is True
    assert first.body == second.body
    async with db_session.transaction() as s:
        orgs = list((await s.execute(select(Organization))).scalars())
    assert len(orgs) == 1


async def test_invalid_inn_rejected() -> None:
    actor = await _bare_actor("u-bad-inn")
    with pytest.raises(ValidationFailed):
        await identity.create_organization(
            actor, _customer_data(inn="7707083894"), idem=_idem("org-create-4")
        )


async def test_unknown_kind_rejected() -> None:
    actor = await _bare_actor("u-bad-kind")
    with pytest.raises(ValidationFailed):
        await identity.create_organization(
            actor, _customer_data(kind="operator"), idem=_idem("org-create-5")
        )


async def test_foreign_inn_grants_no_access_to_existing_organization() -> None:
    """A30: занятый ИНН не блокирует черновик и не открывает чужие данные."""
    owner = await _bare_actor("u-owner")
    await identity.create_organization(
        owner, _customer_data(name="ООО Оригинал", inn=VALID_INN_10), idem=_idem("org-a30-1")
    )
    async with db_session.transaction() as s:
        original = (await s.execute(select(Organization))).scalar_one()
        original_id = original.id

    intruder = await _bare_actor("u-intruder")
    created = await identity.create_organization(
        intruder,
        _customer_data(name="ООО Оригинал", inn=f" {VALID_INN_10} "),
        idem=_idem("org-a30-2"),
    )
    assert created.status == 201
    assert created.body["organization"]["id"] != ids.encode("organization", original_id)

    info = identity.SessionInfo(
        session_id=uuid.uuid4(),
        user_id=intruder.user_id,
        display_name="Нарушитель",
        expires_at=utcnow() + timedelta(hours=1),
    )
    with pytest.raises(NotFound):
        await identity.resolve_actor(info, ids.encode("organization", original_id))


async def test_update_organization_requires_manager() -> None:
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id="u-emp")
        org = await factories.create_organization(s)
        membership = await factories.create_membership(s, user, org, role="customer_employee")
        employee = UserActor(
            user_id=user.id,
            membership_id=membership.id,
            organization_id=org.id,
            role="customer_employee",
            location_ids=frozenset(),
        )
        manager_membership = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="u-mgr"), org
        )
        manager = UserActor(
            user_id=manager_membership.user_id,
            membership_id=manager_membership.id,
            organization_id=org.id,
            role="customer_manager",
        )

    with pytest.raises(Forbidden):
        await identity.update_organization(
            employee, identity.OrganizationUpdateData(name="Новое"), idem=_idem("org-upd-1")
        )

    result = await identity.update_organization(
        manager, identity.OrganizationUpdateData(name="Новое имя"), idem=_idem("org-upd-2")
    )
    assert result.body["name"] == "Новое имя"
    assert (await identity.get_organization(scope_of(manager))).name == "Новое имя"


async def test_update_organization_null_semantics() -> None:
    """ТЗ 10.4: непереданное поле не трогается, явный `null` очищает nullable-поле,
    для `name` (NOT NULL) явный `null` — `ValidationFailed`."""
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        org.contact_email = "old@example.test"
        membership = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="u-mgr-null"), org
        )
        manager = UserActor(
            user_id=membership.user_id,
            membership_id=membership.id,
            organization_id=org.id,
            role="customer_manager",
        )

    untouched = await identity.update_organization(
        manager, identity.OrganizationUpdateData(name="Не трогаем email"), idem=_idem("org-null-1")
    )
    assert untouched.body["contact_email"] == "old@example.test"

    cleared = await identity.update_organization(
        manager, identity.OrganizationUpdateData(contact_email=None), idem=_idem("org-null-2")
    )
    assert cleared.body["contact_email"] is None

    with pytest.raises(ValidationFailed) as exc:
        await identity.update_organization(
            manager, identity.OrganizationUpdateData(name=None), idem=_idem("org-null-3")
        )
    assert exc.value.details.get("field") == "name"
