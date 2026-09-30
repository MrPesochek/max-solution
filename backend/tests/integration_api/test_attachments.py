from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.db import session as db_session
from app.db.models import Organization
from app.infra.config import Settings, get_settings
from app.infra.storage.local import LocalFileStorage
from app.modules.files import api as files
from tests import factories
from tests.files import helpers
from tests.integration_api.conftest import bearer, idem
from tests.requests import helpers as request_helpers
from tests.requests.factories import build_world

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


async def _api_key(organization_id: str | None = None, *, name: str = "CRM") -> str:
    async with db_session.transaction() as session:
        if organization_id is None:
            org = await factories.create_organization(
                session, name="ООО Чужой сервис", customer=False, provider=True
            )
            await factories.create_provider_profile(session, org)
        else:
            org = await session.get(Organization, organization_id)
            assert org is not None
        _client, raw = await factories.create_integration_client(
            session, org, name=name, scopes=("requests:read", "requests:write")
        )
        return raw


async def test_integration_key_downloads_own_request_file(client: AsyncClient) -> None:
    world = await build_world()
    key = await _api_key(world.provider_org_id)
    foreign_key = await _api_key(name="Чужая CRM")

    accepted = await request_helpers.make_accepted(world)
    uploaded = await helpers.upload(
        world.employee,
        files.request_owner(request_helpers.rid(accepted)),
        helpers.jpeg_with_gps(),
        slot="overview",
    )
    await helpers.process()
    attachment_id = uploaded.body["id"]

    mine = await client.get(f"/attachments/{attachment_id}/content", headers=bearer(key))
    assert mine.status_code == 200
    assert mine.headers["x-content-type-options"] == "nosniff"
    assert not helpers.has_gps(mine.content)

    stranger = await client.get(
        f"/attachments/{attachment_id}/content", headers=bearer(foreign_key)
    )
    assert stranger.status_code == 404


async def test_integration_key_uploads_to_assigned_request(client: AsyncClient) -> None:
    world = await build_world()
    key = await _api_key(world.provider_org_id)
    accepted = await request_helpers.make_accepted(world)

    response = await client.post(
        f"/requests/{accepted['id']}/attachments",
        headers={**bearer(key), **idem("api-att-1")},
        files={"file": ("photo.png", helpers.png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["processing_state"] == "quarantined"

    foreign_key = await _api_key(name="Чужая CRM")
    denied = await client.post(
        f"/requests/{accepted['id']}/attachments",
        headers={**bearer(foreign_key), **idem("api-att-2")},
        files={"file": ("photo.png", helpers.png(), "image/png")},
    )
    assert denied.status_code == 404


async def test_upload_idempotency_accounts_for_content(client: AsyncClient) -> None:
    world = await build_world()
    key = await _api_key(world.provider_org_id)
    accepted = await request_helpers.make_accepted(world)
    url = f"/requests/{accepted['id']}/attachments"
    headers = {**bearer(key), **idem("api-att-same")}

    first = await client.post(
        url, headers=headers, files={"file": ("photo.png", helpers.png(), "image/png")}
    )
    assert first.status_code == 201, first.text
    replay = await client.post(
        url, headers=headers, files={"file": ("photo.png", helpers.png(), "image/png")}
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    other = await client.post(
        url, headers=headers, files={"file": ("photo.png", helpers.png((80, 60)), "image/png")}
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_upload_documents_413_and_415(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    responses = schema["paths"]["/requests/{request_id}/attachments"]["post"]["responses"]
    assert {"413", "415"} <= set(responses)
