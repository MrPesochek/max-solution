from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core import ids
from app.db import session as db_session
from app.db.models import User
from app.infra.config import Settings, get_settings
from app.infra.storage.local import LocalFileStorage
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests import factories
from tests.app_api.conftest import auth, idem
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World, build_world

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def file_storage(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    root = tmp_path / "files"
    monkeypatch.setenv("FILE_STORAGE_PATH", str(root))
    get_settings.cache_clear()
    files.set_storage(LocalFileStorage(root))
    yield root
    files.set_storage(None)
    get_settings.cache_clear()


async def _token(world: World) -> dict[str, str]:
    async with db_session.transaction() as session:
        user = await session.get(User, world.employee.user_id)
        assert user is not None
        token = await factories.create_session_token(session, user)
    return auth(token, ids.encode("organization", world.customer_org_id))


async def test_upload_and_download_round_trip(client: AsyncClient) -> None:
    world = await build_world()
    headers = await _token(world)
    draft = await request_helpers.make_draft(world)
    request_id = draft["id"]

    response = await client.post(
        f"/requests/{request_id}/attachments",
        headers={**headers, **idem("att-upload-1")},
        files={"file": ("photo.jpg", helpers.jpeg_with_gps(), "image/jpeg")},
        data={"slot": "overview"},
    )
    assert response.status_code == 201, response.text
    attachment_id = response.json()["id"]
    assert response.json()["processing_state"] == "quarantined"

    assert (
        await client.get(f"/attachments/{attachment_id}/content", headers=headers)
    ).status_code == 404

    await helpers.process()
    content = await client.get(f"/attachments/{attachment_id}/content", headers=headers)
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/jpeg")
    assert content.headers["content-disposition"] == f'inline; filename="{attachment_id}.jpg"'
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["cache-control"] == "private, no-store"
    assert not helpers.has_gps(content.content)

    listing = await client.get(f"/requests/{request_id}/attachments", headers=headers)
    assert [item["id"] for item in listing.json()] == [attachment_id]


async def test_unsupported_type_and_oversized_file(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_world()
    headers = await _token(world)
    draft = await request_helpers.make_draft(world)

    bad = await client.post(
        f"/requests/{draft['id']}/attachments",
        headers={**headers, **idem("att-bad-1")},
        files={"file": ("payload.svg", helpers.not_an_image(), "image/jpeg")},
    )
    assert bad.status_code == 415
    assert bad.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    monkeypatch.setenv("MAX_UPLOAD_BYTES", "512")
    get_settings.cache_clear()
    big = await client.post(
        f"/requests/{draft['id']}/attachments",
        headers={**headers, **idem("att-bad-2")},
        files={"file": ("photo.png", helpers.png((200, 200)), "image/png")},
    )
    assert big.status_code == 413
    assert big.json()["error"]["code"] == "FILE_TOO_LARGE"

    get_settings.cache_clear()
    view = await requests_api.get_request(world.employee, request_helpers.rid(draft))
    assert view.attachments == []


async def test_stranger_gets_404_on_content(client: AsyncClient) -> None:
    world = await build_world()
    stranger = await build_world()
    headers = await _token(world)
    draft = await request_helpers.make_draft(world)
    uploaded = await client.post(
        f"/requests/{draft['id']}/attachments",
        headers={**headers, **idem("att-foreign-1")},
        files={"file": ("photo.png", helpers.png(), "image/png")},
    )
    await helpers.process()
    attachment_id = uploaded.json()["id"]

    foreign_headers = await _token(stranger)
    assert (
        await client.get(f"/attachments/{attachment_id}/content", headers=foreign_headers)
    ).status_code == 404
    assert (
        await client.get(f"/attachments/{attachment_id}", headers=foreign_headers)
    ).status_code == 404


async def test_equipment_photo_upload_list_and_download(client: AsyncClient) -> None:
    world = await build_world()
    headers = await _token(world)

    response = await client.post(
        f"/equipment/{ids.encode('equipment', world.equipment_id)}/photos",
        headers={**headers, **idem("eq-photo-1")},
        files={"file": ("photo.png", helpers.png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner_kind"] == "equipment"
    attachment_id = response.json()["id"]

    await helpers.process()
    listing = await client.get(
        f"/equipment/{ids.encode('equipment', world.equipment_id)}/photos", headers=headers
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [attachment_id]

    content = await client.get(f"/attachments/{attachment_id}/content", headers=headers)
    assert content.status_code == 200


async def test_author_deletes_draft_attachment(client: AsyncClient, file_storage: Path) -> None:
    world = await build_world()
    headers = await _token(world)
    draft = await request_helpers.make_draft(world)
    uploaded = await client.post(
        f"/requests/{draft['id']}/attachments",
        headers={**headers, **idem("att-del-1")},
        files={"file": ("photo.png", helpers.png(), "image/png")},
    )
    attachment_id = uploaded.json()["id"]

    deleted = await client.delete(
        f"/attachments/{attachment_id}", headers={**headers, **idem("att-del-2")}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert helpers.stored_files(file_storage) == []


async def test_equipment_photo_keeps_slot(client: AsyncClient) -> None:
    world = await build_world()
    headers = await _token(world)
    url = f"/equipment/{ids.encode('equipment', world.equipment_id)}/photos"
    for key, slot in (("eq-slot-1", "overview"), ("eq-slot-2", "nameplate")):
        response = await client.post(
            url,
            headers={**headers, **idem(key)},
            files={"file": ("photo.png", helpers.png(), "image/png")},
            data={"slot": slot},
        )
        assert response.status_code == 201, response.text
        assert response.json()["slot"] == slot

    listing = (await client.get(url, headers=headers)).json()
    assert sorted(item["slot"] for item in listing) == ["nameplate", "overview"]
