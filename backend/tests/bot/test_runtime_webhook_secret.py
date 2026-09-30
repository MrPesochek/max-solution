from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from structlog.testing import capture_logs

from app.adapters.bot import (
    build_webhook_router,
    cli,
    ensure_subscription,
    set_runtime,
    webhook_secret,
)
from app.adapters.bot.runtime import BotRuntime, SubscriptionError
from app.adapters.bot.webhook import SECRET_HEADER
from app.core.clock import set_clock
from tests.bot.conftest import WEBHOOK_SECRET, BotHarness, bot_started

NEW_SECRET = "webhook-secret-new-5678"
FOREIGN = "https://other.example/hooks/max"


@dataclass
class FakeMaxApi:
    subscriptions: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    reject_subscribe: int = 0

    def install(self, runtime: BotRuntime) -> None:
        bot: Any = runtime.bot
        bot.get_subscriptions = self.get_subscriptions
        bot.subscribe_webhook = self.subscribe_webhook
        bot.unsubscribe_webhook = self.unsubscribe_webhook

    async def get_subscriptions(self) -> object:
        self.calls.append(("get",))
        items = [SimpleNamespace(url=url, time=0, update_types=None) for url in self.subscriptions]
        return SimpleNamespace(subscriptions=items)

    async def subscribe_webhook(
        self, url: str, update_types: object = None, secret: str | None = None
    ) -> object:
        self.calls.append(("subscribe", url, secret or ""))
        if self.reject_subscribe:
            self.reject_subscribe -= 1
            return SimpleNamespace(success=False, message="временная ошибка")
        self.subscriptions[url] = secret
        return SimpleNamespace(success=True, message=None)

    async def unsubscribe_webhook(self, url: str) -> object:
        self.calls.append(("unsubscribe", url))
        self.subscriptions.pop(url, None)
        return SimpleNamespace(success=True, message=None)

    @property
    def mutations(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] != "get"]


@pytest.fixture
def clock() -> Iterator[list[datetime]]:
    moment = [datetime(2026, 9, 30, 12, 0, tzinfo=UTC)]
    set_clock(lambda: moment[0])
    try:
        yield moment
    finally:
        set_clock(None)


@pytest.fixture
def api() -> FakeMaxApi:
    return FakeMaxApi()


def rotated(runtime: BotRuntime) -> BotRuntime:
    fresh = replace(runtime, secret=NEW_SECRET, previous_secret=runtime.secret)
    set_runtime(fresh)
    return fresh


async def subscribed_with_old_secret(harness: BotHarness, api: FakeMaxApi) -> None:
    api.install(harness.runtime)
    assert await ensure_subscription(harness.runtime) is True
    assert api.subscriptions == {harness.runtime.webhook_url: WEBHOOK_SECRET}
    api.calls.clear()


async def post_event(secret: str | None) -> httpx.Response:
    app = FastAPI()
    app.include_router(build_webhook_router())
    headers = {SECRET_HEADER: secret} if secret is not None else {}
    async with httpx.AsyncClient(
        transport=ASGITransport(app), base_url="https://example.test"
    ) as client:
        return await client.post("/max/webhook", json=bot_started(), headers=headers)


async def test_same_url_new_secret_resubscribes(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)

    assert await ensure_subscription(runtime) is True

    url = runtime.webhook_url
    assert api.mutations == [("unsubscribe", url), ("subscribe", url, NEW_SECRET)]
    assert api.subscriptions == {url: NEW_SECRET}
    state = await webhook_secret.load_state()
    assert state.secret_fp == webhook_secret.fingerprint(NEW_SECRET)
    assert state.replaced_fp == webhook_secret.fingerprint(WEBHOOK_SECRET)
    assert state.pending_fp is None


async def test_unchanged_secret_makes_no_extra_calls(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)

    assert await ensure_subscription(harness.runtime) is False
    assert await ensure_subscription(harness.runtime) is False

    assert api.mutations == []
    assert api.calls == [("get",), ("get",)]


async def test_existing_subscription_without_fingerprint_resubscribes(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    url = harness.runtime.webhook_url
    api.subscriptions = {url: "unknown-secret", FOREIGN: "x"}
    api.install(harness.runtime)

    assert await ensure_subscription(harness.runtime) is True

    assert api.mutations == [("unsubscribe", url), ("subscribe", url, WEBHOOK_SECRET)]
    assert api.subscriptions == {FOREIGN: "x", url: WEBHOOK_SECRET}


async def test_failed_resubscribe_is_retried(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    api.reject_subscribe = 1

    with pytest.raises(SubscriptionError):
        await ensure_subscription(runtime)
    state = await webhook_secret.load_state()
    assert state.secret_fp == webhook_secret.fingerprint(WEBHOOK_SECRET)
    assert state.pending_fp == webhook_secret.fingerprint(NEW_SECRET)

    api.calls.clear()
    assert await ensure_subscription(runtime) is True
    assert api.mutations == [("subscribe", runtime.webhook_url, NEW_SECRET)]
    assert api.subscriptions == {runtime.webhook_url: NEW_SECRET}
    assert await ensure_subscription(runtime) is False


async def test_force_resubscribes_without_reopening_old_secret(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    await ensure_subscription(runtime)
    clock[0] += timedelta(minutes=20)
    api.calls.clear()

    assert await ensure_subscription(runtime, force=True) is True
    url = runtime.webhook_url
    assert api.mutations == [("unsubscribe", url), ("subscribe", url, NEW_SECRET)]
    assert (await post_event(WEBHOOK_SECRET)).status_code == 403


async def test_previous_secret_accepted_until_resubscribe(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    await webhook_secret.mark_rotation_started(
        runtime.webhook_url, webhook_secret.fingerprint(NEW_SECRET)
    )

    with capture_logs() as logs:
        old = await post_event(WEBHOOK_SECRET)
    assert old.status_code == 200
    assert any(
        entry["event"] == "max_webhook_previous_secret_used" and entry["stage"] == "pending"
        for entry in logs
    )
    assert (await post_event(NEW_SECRET)).status_code == 200


async def test_previous_secret_rejected_after_rotation_window(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    await webhook_secret.mark_rotation_started(
        runtime.webhook_url, webhook_secret.fingerprint(NEW_SECRET)
    )

    clock[0] += timedelta(days=1, seconds=1)
    with capture_logs() as logs:
        response = await post_event(WEBHOOK_SECRET)
    assert response.status_code == 403
    assert any(entry["event"] == "max_webhook_previous_secret_rejected" for entry in logs)


async def test_previous_secret_only_for_grace_after_resubscribe(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    await ensure_subscription(runtime)

    clock[0] += timedelta(minutes=5)
    assert (await post_event(WEBHOOK_SECRET)).status_code == 200
    clock[0] += timedelta(minutes=15)
    assert (await post_event(WEBHOOK_SECRET)).status_code == 403
    assert (await post_event(NEW_SECRET)).status_code == 200


async def test_previous_secret_rejected_without_rotation(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    set_runtime(replace(harness.runtime, previous_secret="stale-secret-000"))

    assert (await post_event("stale-secret-000")).status_code == 403
    assert (await post_event(WEBHOOK_SECRET)).status_code == 200


async def test_wrong_secret_rejected_during_rotation(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    await webhook_secret.mark_rotation_started(
        runtime.webhook_url, webhook_secret.fingerprint(NEW_SECRET)
    )

    assert (await post_event("not-the-secret")).status_code == 403
    assert (await post_event(None)).status_code == 403
    assert not harness.transport.sent_messages


async def test_previous_secret_ignored_when_not_configured(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = replace(harness.runtime, secret=NEW_SECRET)
    set_runtime(runtime)
    await webhook_secret.mark_rotation_started(
        runtime.webhook_url, webhook_secret.fingerprint(NEW_SECRET)
    )

    assert (await post_event(WEBHOOK_SECRET)).status_code == 403


async def test_events_keep_flowing_through_rotation(
    harness: BotHarness, api: FakeMaxApi, clock: list[datetime]
) -> None:
    await subscribed_with_old_secret(harness, api)
    url = harness.runtime.webhook_url
    runtime = rotated(harness.runtime)

    await webhook_secret.mark_rotation_started(url, webhook_secret.fingerprint(NEW_SECRET))
    assert (await post_event(api.subscriptions[url])).status_code == 200

    await ensure_subscription(runtime)
    assert (await post_event(api.subscriptions[url])).status_code == 200
    clock[0] += timedelta(hours=2)
    assert (await post_event(api.subscriptions[url])).status_code == 200


async def test_cli_check_and_rotate(
    harness: BotHarness,
    api: FakeMaxApi,
    clock: list[datetime],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await subscribed_with_old_secret(harness, api)
    runtime = rotated(harness.runtime)
    api.install(runtime)
    parser = cli.build_parser()

    assert await cli.run(parser.parse_args(["rotate-webhook-secret", "--check"])) == 2
    assert api.mutations == []
    assert await cli.run(parser.parse_args(["rotate-webhook-secret"])) == 0
    assert api.subscriptions == {runtime.webhook_url: NEW_SECRET}
    assert await cli.run(parser.parse_args(["rotate-webhook-secret", "--check"])) == 0

    output = capsys.readouterr().out
    assert NEW_SECRET not in output
    assert WEBHOOK_SECRET not in output


def test_worker_builds_runtime_for_subscription_check(
    bot_settings: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.bot import runtime as bot_runtime

    monkeypatch.setattr(bot_runtime, "_subscription_runtime", None)
    set_runtime(None)

    built = bot_runtime.subscription_runtime()
    assert built is not None
    assert built.mode == "webhook"
    assert built.secret == WEBHOOK_SECRET
    assert bot_runtime.subscription_runtime() is built
