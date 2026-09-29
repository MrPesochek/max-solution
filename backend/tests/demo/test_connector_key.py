from pathlib import Path

import pytest
from sqlalchemy import update

from app.core.clock import utcnow
from app.core.errors import Unauthenticated
from app.db import session as db_session
from app.db.models import IntegrationClient
from app.demo import seed
from app.modules.integration.keys import authenticate_api_key, parse_api_key
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")

CLIENT_ID = seed._id("integration_client:provider:demo_crm")


def _read(path: Path) -> str:
    return path.read_text().strip()


def _remove(path: Path) -> None:
    path.unlink()


@pytest.fixture
def key_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "demo-secrets" / "connector.key"
    monkeypatch.delenv("CONNECTOR_API_KEY", raising=False)
    monkeypatch.setenv("CONNECTOR_API_KEY_FILE", str(path))
    return path


async def test_first_seed_generates_key_and_second_reuses_it(key_file: Path) -> None:
    report = await seed.run()

    assert report.connector_api_key_generated is True
    assert report.integration_client_created is True
    raw = _read(key_file)
    parsed = parse_api_key(raw)
    assert parsed is not None and parsed.env == "demo"
    actor = await authenticate_api_key(raw)
    assert actor.organization_id == seed.ORG_PROVIDER

    again = await seed.run()
    assert again.connector_api_key_generated is False
    assert _read(key_file) == raw
    assert (await authenticate_api_key(raw)).integration_client_id == CLIENT_ID


async def test_each_stand_gets_its_own_key(key_file: Path, tmp_path: Path) -> None:
    await seed.run()
    first = _read(key_file)
    _remove(key_file)

    await seed.run()
    second = _read(key_file)

    assert first != second
    assert (await authenticate_api_key(second)).integration_client_id == CLIENT_ID
    with pytest.raises(Unauthenticated):
        await authenticate_api_key(first)


async def test_seed_does_not_restore_revoked_client(key_file: Path) -> None:
    await seed.run()
    raw = _read(key_file)
    async with db_session.transaction() as s:
        await s.execute(
            update(IntegrationClient)
            .where(IntegrationClient.id == CLIENT_ID)
            .values(status="revoked", revoked_at=utcnow())
        )

    report = await seed.run()

    assert any("отозван" in note for note in report.notes)
    with pytest.raises(Unauthenticated):
        await authenticate_api_key(raw)
    async with db_session.transaction() as s:
        client = await s.get(IntegrationClient, CLIENT_ID)
        assert client is not None
        assert client.status == "revoked"
        assert client.revoked_at is not None


async def test_published_repository_key_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONNECTOR_API_KEY", "rk_demo_01120116af3a_" + "x" * 43)

    report = await seed.run()

    assert report.integration_client_created is False
    assert any("опубликованным" in note for note in report.notes)
    async with db_session.transaction() as s:
        assert await s.get(IntegrationClient, CLIENT_ID) is None


async def test_explicit_key_still_supported() -> None:
    report = await seed.run()
    assert report.integration_client_created is True
    assert report.connector_api_key_generated is False


async def test_demo_key_rejected_in_prod(key_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed.run()
    raw = _read(key_file)

    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="prod"):
        with pytest.raises(Unauthenticated):
            await authenticate_api_key(raw)
