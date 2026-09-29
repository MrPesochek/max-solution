import uuid

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import (
    City,
    District,
    Organization,
    ProviderCategory,
    ProviderServiceArea,
    VerificationCase,
)
from app.modules.providers import api as providers
from tests import factories
from tests.support import PROVIDER_INN, idem, make_customer, make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def _directories() -> tuple[str, str, str | None]:
    async with db_session.transaction() as s:
        category = await factories.seed_category(s)
        city = await factories.seed_city(s)
        district = await factories.seed_district(s, city)
        return (
            ids.encode("category", category.id),
            ids.encode("city", city.id),
            ids.encode("district", district.id) if district else None,
        )


async def test_self_registration_gives_no_verified_marks() -> None:
    """A02: саморегистрация не выдаёт ни одного признака проверки."""
    provider = await make_provider("prof-a02")
    view = await providers.get_own_profile(scope_of(provider.admin))

    assert view.status == "draft"
    assert [badge.confirmed for badge in view.verification] == [False, False]
    assert all(badge.source is None for badge in view.verification)
    assert not any(getattr(badge, "verified", False) for badge in view.verification)

    with pytest.raises(NotFound):
        await providers.get_public_profile(provider.organization_id)
    items, _ = await providers.list_catalog()
    assert items == []


async def test_update_and_submit_opens_verification_cases() -> None:
    provider = await make_provider("prof-submit", with_category=False, with_area=False)
    category_id, city_id, district_id = await _directories()

    await providers.update_profile(
        provider.admin,
        providers.ProviderProfileUpdateData(
            provider_kind="independent_specialist",
            legal_form="ip",
            inn=PROVIDER_INN,
            contact_name="Иван",
            contact_phone="+79990000000",
            visit_terms="Выезд в течение дня",
            can_provide_documents=True,
            description="Опыт 10 лет",
            category_ids=[category_id],
            service_areas=[
                providers.ServiceAreaInput(
                    city_id=city_id, district_ids=[district_id] if district_id else []
                )
            ],
            brand_restrictions=[
                providers.BrandRestrictionInput(equipment_category_id=category_id, brands=["Бренд"])
            ],
        ),
        idem=idem("prof-upd"),
    )

    result = await providers.submit_for_review(provider.admin, idem=idem("prof-sub"))
    assert result.body["status"] == "pending_review"

    async with db_session.transaction() as s:
        cases = list(
            (
                await s.execute(
                    select(VerificationCase).where(
                        VerificationCase.organization_id == provider.organization_id
                    )
                )
            ).scalars()
        )
        org = await s.get(Organization, provider.organization_id)
        assert org is not None
        categories = list(
            (
                await s.execute(
                    select(ProviderCategory).where(
                        ProviderCategory.provider_org_id == provider.organization_id
                    )
                )
            ).scalars()
        )
        areas = list(
            (
                await s.execute(
                    select(ProviderServiceArea).where(
                        ProviderServiceArea.provider_org_id == provider.organization_id
                    )
                )
            ).scalars()
        )
    assert {case.check_kind for case in cases} == {"requisites", "representative"}
    assert all(case.decision == "pending" for case in cases)
    assert org.details_verification_status == "pending"
    assert org.representative_verification_status == "pending"
    assert len(categories) == 1
    assert len(areas) == 1


async def test_update_rejects_unknown_city() -> None:
    provider = await make_provider("prof-bad-city", with_area=False)
    bogus_city = ids.encode("city", uuid.uuid4())
    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(
                service_areas=[providers.ServiceAreaInput(city_id=bogus_city)]
            ),
            idem=idem("prof-bad-city"),
        )
    assert exc.value.details.get("field") == "city_id"


async def test_update_rejects_district_from_another_city() -> None:
    provider = await make_provider("prof-bad-district", with_area=False)
    _category_id, city_id, _district_id = await _directories()
    async with db_session.transaction() as s:
        other_city = City(name="Другой город")
        s.add(other_city)
        await s.flush()
        other_district = District(city_id=other_city.id, name="Чужой район")
        s.add(other_district)
        await s.flush()
        other_district_id = other_district.id
    foreign_district_id = ids.encode("district", other_district_id)

    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(
                service_areas=[
                    providers.ServiceAreaInput(city_id=city_id, district_ids=[foreign_district_id])
                ]
            ),
            idem=idem("prof-bad-district"),
        )
    assert exc.value.details.get("field") == "district_ids"


async def test_update_rejects_unknown_category() -> None:
    provider = await make_provider("prof-bad-category", with_category=False)
    bogus_category = ids.encode("category", uuid.uuid4())
    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(category_ids=[bogus_category]),
            idem=idem("prof-bad-category"),
        )
    assert exc.value.details.get("field") == "category_ids"


async def test_update_rejects_unknown_category_in_brand_restriction() -> None:
    provider = await make_provider("prof-bad-brand")
    bogus_category = ids.encode("category", uuid.uuid4())
    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(
                brand_restrictions=[
                    providers.BrandRestrictionInput(
                        equipment_category_id=bogus_category, brands=["Бренд"]
                    )
                ]
            ),
            idem=idem("prof-bad-brand"),
        )
    assert exc.value.details.get("field") == "equipment_category_id"


async def test_update_null_semantics() -> None:
    """ТЗ 10.4: непереданное поле не трогается, явный `null` очищает nullable-поле,
    для `provider_kind`/`can_provide_documents` (NOT NULL) — `ValidationFailed`."""
    provider = await make_provider("prof-null")
    await providers.update_profile(
        provider.admin,
        providers.ProviderProfileUpdateData(visit_terms="Выезд в течение дня"),
        idem=idem("prof-null-set"),
    )

    untouched = await providers.update_profile(
        provider.admin,
        providers.ProviderProfileUpdateData(description="Новое описание"),
        idem=idem("prof-null-untouched"),
    )
    assert untouched.body["visit_terms"] == "Выезд в течение дня"

    cleared = await providers.update_profile(
        provider.admin,
        providers.ProviderProfileUpdateData(visit_terms=None),
        idem=idem("prof-null-clear"),
    )
    assert cleared.body["visit_terms"] is None

    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(provider_kind=None),
            idem=idem("prof-null-reject-1"),
        )
    assert exc.value.details.get("field") == "provider_kind"

    with pytest.raises(ValidationFailed) as exc:
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(can_provide_documents=None),
            idem=idem("prof-null-reject-2"),
        )
    assert exc.value.details.get("field") == "can_provide_documents"


async def test_submit_requires_category_and_territory() -> None:
    provider = await make_provider("prof-empty", with_category=False, with_area=False)
    with pytest.raises(ValidationFailed):
        await providers.submit_for_review(provider.admin, idem=idem("prof-sub-2"))


async def test_requisites_are_locked_after_submit() -> None:
    provider = await make_provider("prof-lock")
    await providers.submit_for_review(provider.admin, idem=idem("prof-lock-sub"))

    with pytest.raises(InvalidTransition):
        await providers.update_profile(
            provider.admin,
            providers.ProviderProfileUpdateData(inn=PROVIDER_INN),
            idem=idem("prof-lock-upd"),
        )


async def test_accepting_toggle_only_for_active_profile() -> None:
    provider = await make_provider("prof-acc")
    with pytest.raises(InvalidTransition):
        await providers.set_accepting_new_requests(provider.admin, True, idem=idem("acc-1"))

    active = await make_provider("prof-acc-2", status="active", accepting=False, verified=True)
    result = await providers.set_accepting_new_requests(active.admin, True, idem=idem("acc-2"))
    assert result.body["accepting_new_requests"] is True


async def test_only_provider_admin_edits_profile() -> None:
    provider = await make_provider("prof-role")
    with pytest.raises(Forbidden):
        await providers.update_profile(
            provider.dispatcher,
            providers.ProviderProfileUpdateData(description="нет"),
            idem=idem("prof-role-1"),
        )
    customer = await make_customer("prof-role-c")
    with pytest.raises(Forbidden):
        await providers.update_profile(
            customer.manager,
            providers.ProviderProfileUpdateData(description="нет"),
            idem=idem("prof-role-2"),
        )


async def test_customer_scope_has_no_provider_profile() -> None:
    customer = await make_customer("prof-scope")
    with pytest.raises(Forbidden):
        await providers.get_own_profile(scope_of(customer.manager))


async def test_public_profile_shows_separate_marks_with_source_and_date() -> None:
    """ТЗ 6.4: каждый признак — со своей расшифровкой, источником и датой."""
    provider = await make_provider("prof-pub", status="active", accepting=True, verified=True)
    async with db_session.transaction() as s:
        org = await s.get(Organization, provider.organization_id)
        assert org is not None
        await factories.create_verification_case(
            s,
            org,
            check_kind="requisites",
            decision="approved",
            source="ЕГРЮЛ",
            is_demo=True,
        )
        await factories.create_verification_case(
            s,
            org,
            check_kind="representative",
            subject_type="representative",
            decision="approved",
            source="обратный звонок",
            is_demo=True,
        )

    view = await providers.get_public_profile(provider.organization_id)
    kinds = {badge.kind: badge for badge in view.verification}
    assert kinds["requisites"].confirmed and kinds["representative"].confirmed
    assert kinds["requisites"].title == "Реквизиты проверены"
    assert kinds["requisites"].source == "ЕГРЮЛ"
    assert kinds["requisites"].is_demo is True
    assert kinds["requisites"].limitation
    assert view.rating is None
    assert view.gallery == []
    assert view.specialization_disclaimer == "Со слов исполнителя"
    assert not hasattr(view, "inn")


async def test_profile_reports_portfolio_limit_of_ten() -> None:
    """ТЗ 14.1 / design-specification: галерея — до 10 изображений, лимит задаёт сервер."""
    provider = await make_provider("prof-gallery")
    view = await providers.get_own_profile(scope_of(provider.admin))
    assert view.portfolio_max_images == 10


@pytest.mark.parametrize("status", ["pending_review", "active"])
async def test_change_specialization_and_city_after_registration(status: str) -> None:
    from app.db.models import EquipmentCategory

    provider = await make_provider(f"edit-{status}", status=status)
    before = await providers.get_own_profile(scope_of(provider.admin))
    async with db_session.transaction() as session:
        cities = (await session.execute(select(City))).scalars().all()
        categories = (await session.execute(select(EquipmentCategory))).scalars().all()
        city = next(
            c for c in cities if ids.encode("city", c.id) != before.service_areas[0].city_id
        )
        category = next(
            c for c in categories if ids.encode("category", c.id) != before.categories[0].id
        )
        city_id, category_id = ids.encode("city", city.id), ids.encode("category", category.id)
    data = providers.ProviderProfileUpdateData(
        category_ids=[category_id],
        service_areas=[providers.ServiceAreaInput(city_id=city_id, district_ids=[])],
    )
    await providers.update_profile(provider.admin, data, idem=None)
    after = await providers.get_own_profile(scope_of(provider.admin))
    assert after.status == status
    assert [c.id for c in after.categories] == [category_id]
    assert [(a.city_id, a.district_id) for a in after.service_areas] == [(city_id, None)]
    with pytest.raises(InvalidTransition):
        await providers.update_profile(
            provider.admin, providers.ProviderProfileUpdateData(inn=PROVIDER_INN), idem=None
        )
    with pytest.raises(Forbidden):
        await providers.update_profile(provider.dispatcher, data, idem=None)
