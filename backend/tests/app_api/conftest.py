from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.infra.config import Settings
from app.main import create_app
from tests import factories

BASE_URL = "http://testserver/app-api/v1"


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(monkeypatch)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as http:
        yield http


def auth(token: str, organization_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization_id:
        headers["X-Organization-Id"] = organization_id
    return headers


def idem(key: str) -> dict[str, str]:
    return {"Idempotency-Key": f"test-key-{key}"}
