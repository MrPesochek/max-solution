import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import UserActor
from app.db.models import Organization
from app.infra.config import Settings
from tests import factories


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.integration_settings(monkeypatch)


@dataclass
class ReceivedWebhook:
    headers: dict[str, str]
    body: bytes


@dataclass
class Receiver:
    """Локальный приёмник: запоминает запросы и отдаёт заранее заданные коды ответа."""

    url: str = ""
    received: list[ReceivedWebhook] = field(default_factory=list)
    statuses: deque[int] = field(default_factory=deque)
    default_status: int = 200

    def respond_with(self, *statuses: int) -> None:
        self.statuses.extend(statuses)

    def next_status(self) -> int:
        return self.statuses.popleft() if self.statuses else self.default_status


@pytest_asyncio.fixture
async def receiver() -> AsyncIterator[Receiver]:
    state = Receiver()
    app = FastAPI()

    @app.post("/hooks")
    async def hook(request: Request) -> Response:
        state.received.append(
            ReceivedWebhook(headers=dict(request.headers), body=await request.body())
        )
        return Response(status_code=state.next_status())

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn.Server не даёт события «запущен»
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    state.url = f"http://127.0.0.1:{port}/hooks"
    try:
        yield state
    finally:
        server.should_exit = True
        await task


async def provider_org(session: AsyncSession, *, name: str = "ООО Сервис") -> Organization:
    org = await factories.create_organization(session, name=name, customer=False, provider=True)
    await factories.create_provider_profile(session, org)
    return org


async def provider_admin(session: AsyncSession, org: Organization) -> UserActor:
    user = await factories.create_user(session)
    membership = await factories.create_membership(session, user, org, role="provider_admin")
    return UserActor(
        user_id=user.id,
        membership_id=membership.id,
        organization_id=org.id,
        role="provider_admin",
    )
