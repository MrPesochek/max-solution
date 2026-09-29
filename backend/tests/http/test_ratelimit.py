from collections.abc import Iterator

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport

from app.adapters.http.errors import install_error_handlers
from app.adapters.http.ratelimit import SlidingWindowLimiter, limit_auth_attempts
from app.infra.config import Settings
from tests import factories


def test_window_slides() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    assert all(limiter.hit("ip", limit=3, window=10) for _ in range(3))
    assert not limiter.hit("ip", limit=3, window=10)
    assert limiter.hit("other", limit=3, window=10)
    now[0] = 10.5
    assert limiter.hit("ip", limit=3, window=10)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(
        monkeypatch, AUTH_RATE_LIMIT_ATTEMPTS="2", AUTH_RATE_LIMIT_WINDOW_SECONDS="60"
    )


async def test_endpoint_answers_429_after_limit(settings: Settings) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/auth/max", dependencies=[Depends(limit_auth_attempts)])
    async def login() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(transport=ASGITransport(app), base_url="http://t") as client:
        codes = [(await client.post("/auth/max")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
