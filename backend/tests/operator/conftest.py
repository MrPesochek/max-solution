from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.infra.config import Settings
from app.main import create_app
from tests import factories

BASE_URL = "http://testserver/operator-api/v1"


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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def idem_header(key: str) -> dict[str, str]:
    return {"Idempotency-Key": f"op-key-{key}"}
