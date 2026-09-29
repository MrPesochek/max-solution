from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.integration_api import deps
from app.db.models import Organization
from app.infra.config import Settings
from app.main import create_app
from tests import factories
from tests.worker.conftest import Receiver, receiver

API_URL = "http://testserver/api/v1"
APP_API_URL = "http://testserver/app-api/v1"


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.integration_settings(monkeypatch)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    deps.reset_limiter()
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_URL) as http:
        yield http


@pytest_asyncio.fixture
async def app_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=APP_API_URL) as http:
        yield http


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def idem(key: str) -> dict[str, str]:
    return {"Idempotency-Key": f"test-key-{key}"}


async def provider_org(session: AsyncSession, *, name: str = "ООО Сервис") -> Organization:
    org = await factories.create_organization(session, name=name, customer=False, provider=True)
    await factories.create_provider_profile(session, org)
    return org


__all__ = ["API_URL", "APP_API_URL", "Receiver", "bearer", "idem", "provider_org", "receiver"]
