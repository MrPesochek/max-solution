import pytest
from sqlalchemy import update

from app.core import ids
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Attachment, ServiceBinding, WebhookSubscription
from app.modules.catalog import api as catalog
from app.modules.requests import api as requests_api
from app.modules.trust import api as trust
from tests.requests import factories
from tests.requests import helpers as h
from tests.support import idem

pytestmark = pytest.mark.usefixtures("clean_db")


async def _subscribe(world: factories.World) -> None:
    async with db_session.transaction() as session:
        session.add(
            WebhookSubscription(
                integration_client_id=world.integration.integration_client_id,
                provider_org_id=world.provider_org_id,
                url="https://crm.secret.example/hook",
                event_types=["request.assigned"],
                secret_encrypted=b"secret",
            )
        )


async def test_summary_has_binding_request_and_nameplate() -> None:
    world = await factories.build_world()
    items, _ = await catalog.list_equipment(scope_of(world.manager))
    by_id = {i.id: i for i in items}
    main = by_id[ids.encode("equipment", world.equipment_id)]
    other = by_id[ids.encode("equipment", world.other_equipment_id)]
    assert main.category_code and main.category_name
    assert main.location_name == "Кафе на Ленина"
    assert main.binding is not None
    assert main.binding.status == "confirmed"
    assert main.binding.provider_name == "Холод-Сервис"
    assert main.binding.is_contact_only is False
    assert main.binding.provider_has_crm is False
    assert main.active_request is None
    assert main.has_nameplate_photo is False
    assert other.binding is None

    await _subscribe(world)
    submitted = await h.make_submitted(world)
    async with db_session.transaction() as session:
        session.add(
            Attachment(
                owner_kind="equipment",
                equipment_id=world.equipment_id,
                slot="nameplate",
                visibility_class="request_private",
                mime_type="image/jpeg",
                byte_size=10,
                storage_key="test/nameplate",
                processing_state="ready",
            )
        )

    view = await catalog.get_equipment(scope_of(world.manager), world.equipment_id)
    assert view.binding is not None and view.binding.provider_has_crm is True
    assert view.active_request is not None
    assert view.active_request.id == submitted["id"]
    assert view.active_request.status == "awaiting_provider"
    assert view.has_nameplate_photo is True
    assert "crm.secret.example" not in view.model_dump_json()


async def test_summary_skips_rejected_binding_and_prefers_confirmed() -> None:
    world = await factories.build_world(binding_status="pending")
    view = await catalog.get_equipment(scope_of(world.manager), world.equipment_id)
    assert view.binding is not None and view.binding.status == "pending"

    async with db_session.transaction() as session:
        await session.execute(
            update(ServiceBinding)
            .where(ServiceBinding.id == world.binding_id)
            .values(status="rejected")
        )
    view = await catalog.get_equipment(scope_of(world.manager), world.equipment_id)
    assert view.binding is None


async def test_personal_contact_is_not_hidden_by_pending_binding() -> None:
    """«Мой контакт» заказчик подтвердил сам — он важнее незавершённого запроса привязки,
    но уступает подтверждённой привязке сервиса."""
    world = await factories.build_world(binding_status="pending")
    await trust.create_contact_binding(
        world.manager,
        trust.ContactBindingData(
            equipment_id=ids.encode("equipment", world.equipment_id),
            contact_name="Мастер Пётр",
            contact_phone="+7 900 000-00-01",
        ),
        idem=idem("summary-contact"),
    )
    view = await catalog.get_equipment(scope_of(world.manager), world.equipment_id)
    assert view.binding is not None
    assert view.binding.is_contact_only is True
    assert view.binding.provider_name == "Мастер Пётр"
    assert view.binding.contact_phone == "+7 900 000-00-01"

    async with db_session.transaction() as session:
        await session.execute(
            update(ServiceBinding)
            .where(ServiceBinding.id == world.binding_id)
            .values(status="confirmed")
        )
    view = await catalog.get_equipment(scope_of(world.manager), world.equipment_id)
    assert view.binding is not None
    assert view.binding.is_contact_only is False
    assert view.binding.provider_name == "Холод-Сервис"
    assert view.binding.contact_phone is None


async def test_employee_summary_is_limited_to_own_locations() -> None:
    world = await factories.build_world()
    items, _ = await catalog.list_equipment(scope_of(world.employee))
    assert {i.id for i in items} == {ids.encode("equipment", world.equipment_id)}
    await requests_api.create_draft(
        world.manager, equipment_id=world.other_equipment_id, symptom_description="Шумит"
    )
    items, _ = await catalog.list_equipment(scope_of(world.other_employee))
    assert items[0].active_request is not None
    items, _ = await catalog.list_equipment(scope_of(world.employee))
    assert items[0].active_request is None


async def test_foreign_customer_sees_no_summary() -> None:
    world = await factories.build_world()
    foreign = await factories.build_foreign_world()
    items, _ = await catalog.list_equipment(scope_of(foreign.manager))
    assert ids.encode("equipment", world.equipment_id) not in {i.id for i in items}
