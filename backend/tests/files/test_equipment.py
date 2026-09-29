from collections.abc import Callable

import pytest

from app.core.errors import NotFound, ValidationFailed
from app.db.enums import VisibilityClass
from app.infra.config import Settings
from app.modules.files import api as files
from tests.files import helpers
from tests.requests.factories import World, build_world

pytestmark = pytest.mark.usefixtures("clean_db")


async def _uploaded_photo(world: World) -> str:
    result = await helpers.upload(
        world.employee, files.equipment_owner(world.equipment_id), helpers.png()
    )
    await helpers.process()
    return result.body["id"]


async def test_manager_and_employee_of_the_location_can_upload(world: World) -> None:
    result = await helpers.upload(
        world.manager, files.equipment_owner(world.equipment_id), helpers.png()
    )
    assert result.body["visibility_class"] == VisibilityClass.REQUEST_PRIVATE
    assert result.body["owner_kind"] == "equipment"

    result = await helpers.upload(
        world.employee, files.equipment_owner(world.equipment_id), helpers.png()
    )
    assert result.status == 201


async def test_employee_of_other_location_cannot_upload(world: World) -> None:
    with pytest.raises(NotFound):
        await helpers.upload(
            world.other_employee, files.equipment_owner(world.equipment_id), helpers.png()
        )


async def test_provider_cannot_upload(world: World) -> None:
    with pytest.raises(NotFound):
        await helpers.upload(
            world.dispatcher, files.equipment_owner(world.equipment_id), helpers.png()
        )


async def test_foreign_customer_cannot_upload(world: World, other_world: World) -> None:
    with pytest.raises(NotFound):
        await helpers.upload(
            other_world.manager, files.equipment_owner(world.equipment_id), helpers.png()
        )


async def test_photo_limit_per_equipment(world: World, override: Callable[..., Settings]) -> None:
    override(MAX_PHOTOS_PER_EQUIPMENT="1")
    await helpers.upload(world.manager, files.equipment_owner(world.equipment_id), helpers.png())
    with pytest.raises(ValidationFailed) as exc:
        await helpers.upload(
            world.manager, files.equipment_owner(world.equipment_id), helpers.png()
        )
    assert exc.value.code == "EQUIPMENT_PHOTO_LIMIT_REACHED"


async def test_customer_participants_see_photo_within_location(world: World) -> None:
    photo_id = await _uploaded_photo(world)
    attachment_id = helpers.aid({"id": photo_id})
    for actor in (world.manager, world.employee):
        content = await files.open_attachment(actor, attachment_id)
        assert content.byte_size > 0
    listed = await files.list_for_equipment(world.manager, world.equipment_id)
    assert [item.id for item in listed] == [photo_id]


async def test_employee_of_other_location_does_not_see(world: World) -> None:
    photo_id = await _uploaded_photo(world)
    attachment_id = helpers.aid({"id": photo_id})
    with pytest.raises(NotFound):
        await files.open_attachment(world.other_employee, attachment_id)
    assert await files.list_for_equipment(world.other_employee, world.equipment_id) == []


async def test_foreign_organization_gets_not_found(world: World, other_world: World) -> None:
    photo_id = await _uploaded_photo(world)
    attachment_id = helpers.aid({"id": photo_id})
    with pytest.raises(NotFound):
        await files.get_attachment(other_world.manager, attachment_id)
    with pytest.raises(NotFound):
        await files.open_attachment(other_world.dispatcher, attachment_id)


async def test_provider_without_confirmed_binding_does_not_see() -> None:
    world = await build_world(binding_status="pending")
    photo_id = await _uploaded_photo(world)
    attachment_id = helpers.aid({"id": photo_id})
    with pytest.raises(NotFound):
        await files.open_attachment(world.dispatcher, attachment_id)
    with pytest.raises(NotFound):
        await files.open_attachment(world.integration, attachment_id)
    assert await files.list_for_equipment(world.dispatcher, world.equipment_id) == []


async def test_provider_with_confirmed_binding_sees(world: World) -> None:
    photo_id = await _uploaded_photo(world)
    attachment_id = helpers.aid({"id": photo_id})
    for actor in (world.dispatcher, world.provider_admin, world.integration):
        content = await files.open_attachment(actor, attachment_id)
        assert content.byte_size > 0
    listed = await files.list_for_equipment(world.dispatcher, world.equipment_id)
    assert [item.id for item in listed] == [photo_id]


async def test_author_or_manager_deletes_photo(world: World) -> None:
    uploaded = await helpers.upload(
        world.employee, files.equipment_owner(world.equipment_id), helpers.png()
    )
    attachment_id = helpers.aid(uploaded.body)

    with pytest.raises(NotFound):
        await files.delete_attachment(world.other_employee, attachment_id)

    await files.delete_attachment(world.manager, attachment_id)

    again = await helpers.upload(
        world.employee, files.equipment_owner(world.equipment_id), helpers.png()
    )
    await files.delete_attachment(world.employee, helpers.aid(again.body))
