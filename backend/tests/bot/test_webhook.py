import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import build_runtime, build_webhook_router, set_runtime
from app.adapters.bot.webhook import SECRET_HEADER
from app.db.models import MaxUpdate, User
from app.infra.config import Settings
from tests.bot.conftest import WEBHOOK_SECRET, BotHarness, bot_started, message_created
from tests.factories import apply_test_settings


@pytest.fixture
def webhook_app(harness: BotHarness) -> FastAPI:
    app = FastAPI()
    app.include_router(build_webhook_router())
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app), base_url="https://example.test")


async def test_webhook_rejects_wrong_secret(webhook_app: FastAPI, harness: BotHarness) -> None:
    async with client_for(webhook_app) as client:
        without = await client.post("/max/webhook", json=bot_started())
        wrong = await client.post(
            "/max/webhook", json=bot_started(), headers={SECRET_HEADER: "not-the-secret"}
        )
    assert without.status_code == 403
    assert wrong.status_code == 403
    assert without.content == b""
    assert not harness.transport.sent_messages


async def test_webhook_accepts_correct_secret(webhook_app: FastAPI, harness: BotHarness) -> None:
    async with client_for(webhook_app) as client:
        response = await client.post(
            "/max/webhook", json=bot_started(), headers={SECRET_HEADER: WEBHOOK_SECRET}
        )
    assert response.status_code == 200
    assert harness.transport.sent_messages


async def test_webhook_unknown_update_type_answered(webhook_app: FastAPI) -> None:
    async with client_for(webhook_app) as client:
        response = await client.post(
            "/max/webhook",
            json={"update_type": "quantum_event", "timestamp": 1},
            headers={SECRET_HEADER: WEBHOOK_SECRET},
        )
    assert response.status_code == 200


async def test_duplicate_update_processed_once(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    """A16: повтор события не выполняет обработчик второй раз."""
    event = message_created("/start")

    first = await harness.deliver(event)
    sent_after_first = len(harness.transport.sent_messages)
    second = await harness.deliver(event)

    assert first.duplicate is False
    assert second.duplicate is True
    assert len(harness.transport.sent_messages) == sent_after_first
    rows = await db_session.scalar(select(func.count()).select_from(MaxUpdate))
    assert rows == 1


async def test_update_recorded_and_marked_processed(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    await harness.deliver(message_created("/help"))
    row = (await db_session.execute(select(MaxUpdate))).scalar_one()
    assert row.update_type == "message_created"
    assert row.processed_at is not None
    assert row.processing_error is None


async def test_bot_started_creates_user(harness: BotHarness, db_session: AsyncSession) -> None:
    await harness.deliver(bot_started())
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.bot_available is True
    assert user.bot_started_at is not None


async def test_bot_stopped_clears_availability(
    harness: BotHarness, db_session: AsyncSession
) -> None:
    from tests.bot.conftest import bot_stopped

    await harness.deliver(bot_started())
    await harness.deliver(bot_stopped())
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.bot_available is False


async def test_handler_failure_is_answered_with_200(
    webhook_app: FastAPI,
    harness: BotHarness,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка обработчика не вызывает бесконечные повторы: 200 и отметка в журнале."""

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("сценарий сломался")

    monkeypatch.setattr("app.adapters.bot.menu.send_menu", boom)

    async with client_for(webhook_app) as client:
        response = await client.post(
            "/max/webhook",
            json=message_created("/start"),
            headers={SECRET_HEADER: WEBHOOK_SECRET},
        )

    assert response.status_code == 200
    row = (await db_session.execute(select(MaxUpdate))).scalar_one()
    assert row.processing_error == "RuntimeError"


async def test_ensure_subscription_is_idempotent(harness: BotHarness) -> None:
    from app.adapters.bot import ensure_subscription

    subscribed: list[str] = []

    class _Subs:
        def __init__(self, urls: list[str]) -> None:
            self.subscriptions = [
                type("S", (), {"url": url, "time": 0, "update_types": None})() for url in urls
            ]

    async def get_subscriptions() -> object:
        return _Subs(subscribed.copy())

    async def subscribe_webhook(url: str, secret: str | None = None, **kwargs: object) -> None:
        subscribed.append(url)

    harness.runtime.bot.get_subscriptions = get_subscriptions  # type: ignore[method-assign]
    harness.runtime.bot.subscribe_webhook = subscribe_webhook  # type: ignore[method-assign,assignment]

    assert await ensure_subscription(harness.runtime) is True
    assert await ensure_subscription(harness.runtime) is False
    assert subscribed == [harness.runtime.webhook_url]


async def test_ensure_subscription_removes_stale_own_webhooks(harness: BotHarness) -> None:
    from app.adapters.bot import ensure_subscription

    stale = "https://old-host.example/max/webhook"
    foreign = "https://other.example/hooks/max"
    subscribed = [stale, foreign]
    removed: list[str] = []

    class _Subs:
        def __init__(self, urls: list[str]) -> None:
            self.subscriptions = [
                type("S", (), {"url": url, "time": 0, "update_types": None})() for url in urls
            ]

    async def get_subscriptions() -> object:
        return _Subs(subscribed.copy())

    async def subscribe_webhook(url: str, secret: str | None = None, **kwargs: object) -> None:
        subscribed.append(url)

    async def unsubscribe_webhook(url: str) -> None:
        removed.append(url)
        subscribed.remove(url)

    harness.runtime.bot.get_subscriptions = get_subscriptions  # type: ignore[method-assign]
    harness.runtime.bot.subscribe_webhook = subscribe_webhook  # type: ignore[method-assign,assignment]
    harness.runtime.bot.unsubscribe_webhook = unsubscribe_webhook  # type: ignore[method-assign,assignment]

    assert await ensure_subscription(harness.runtime) is True
    assert removed == [stale]
    assert subscribed == [foreign, harness.runtime.webhook_url]


async def test_off_mode_starts_app_without_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стенд без MAX: приложение поднимается, маршрута вебхука нет."""
    from app.main import create_app

    for value in apply_test_settings(monkeypatch, MAX_UPDATES_MODE="off", MAX_BOT_TOKEN=""):
        assert build_runtime(value) is None
        app = create_app()
        async with client_for(app) as client:
            health = await client.get("/healthz")
            webhook = await client.post("/max/webhook", json=bot_started())
        assert health.status_code == 200
        assert webhook.status_code == 404


async def test_webhook_without_configured_secret_rejects_outside_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in apply_test_settings(
        monkeypatch, APP_ENV="demo", MAX_UPDATES_MODE="webhook", MAX_WEBHOOK_SECRET=""
    ):
        runtime = build_runtime(value)
        assert runtime is not None
        set_runtime(runtime)
        try:
            app = FastAPI()
            app.include_router(build_webhook_router())
            async with client_for(app) as client:
                response = await client.post("/max/webhook", json=bot_started())
            assert response.status_code == 403
        finally:
            set_runtime(None)


def test_prod_refuses_webhook_mode_without_secret() -> None:
    with pytest.raises(ValueError, match="MAX_WEBHOOK_SECRET"):
        Settings(
            app_env="prod",
            max_bot_token="t",
            max_updates_mode="webhook",
            max_webhook_secret="",
            demo_login_enabled=False,
        )
