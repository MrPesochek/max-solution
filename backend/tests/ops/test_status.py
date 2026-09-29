from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MaxUpdate, Notification, WebhookDelivery
from app.infra.config import Settings
from app.main import create_app
from app.modules.ops import api as ops
from app.worker import ops_monitor
from tests import factories
from tests.ops.conftest import Clock

pytestmark = pytest.mark.usefixtures("db_session")

OPS_TOKEN = "ops-test-token-1234567890"
EXTERNAL = ("203.0.113.7", 40000)
INTERNAL = ("172.30.57.20", 40000)
REPO_DIR = Path(__file__).resolve().parents[3]


async def _healthy_worker(settings: Settings, clock: Clock) -> None:
    writer = ops.HeartbeatWriter.for_loops({"notification_dispatcher": 1.0}, settings)
    await writer.register(clock.now)
    await writer.succeeded("notification_dispatcher", clock.now, 0)


def _codes(status: ops.OpsStatus) -> set[str]:
    return {alarm.code for alarm in status.alarms}


async def _old_notification(session: AsyncSession, age: timedelta, clock: Clock) -> None:
    user = await factories.create_user(session)
    notification = await factories.create_notification(session, user)
    await session.execute(
        update(Notification)
        .where(Notification.id == notification.id)
        .values(created_at=clock.now - age)
    )
    await session.commit()


async def _webhook(
    session: AsyncSession, *, state: str, next_attempt_in: timedelta, clock: Clock
) -> WebhookDelivery:
    org = await factories.create_organization(session, customer=False, provider=True)
    client, _ = await factories.create_integration_client(session, org)
    subscription = await factories.create_webhook_subscription(session, client)
    event = await factories.create_integration_event(session, org)
    delivery = await factories.create_webhook_delivery(
        session, event, subscription, state=state, next_attempt_at=clock.now + next_attempt_in
    )
    await session.commit()
    return delivery


async def test_quiet_platform_is_not_degraded(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    await _old_notification(db_session, timedelta(seconds=30), clock)

    status = await ops.collect_status(clock.now, settings)

    assert status.degraded is False
    body = status.to_json()
    assert body["notifications"]["pending"] == 1
    assert body["notifications"]["oldest_pending_age_seconds"] == 30
    assert body["heartbeats"][0]["loop"] == "notification_dispatcher"


async def test_old_pending_notification_is_degraded(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    await _old_notification(db_session, timedelta(hours=1), clock)

    status = await ops.collect_status(clock.now, settings)

    assert status.degraded is True
    assert _codes(status) == {"notification_backlog_stale"}
    reason = status.to_json()["reasons"][0]
    assert reason["age_seconds"] == 3600
    assert reason["threshold_seconds"] == settings.ops_notification_max_age_seconds


async def test_overdue_webhook_is_degraded_but_scheduled_retry_is_not(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    await _webhook(db_session, state="retrying", next_attempt_in=timedelta(minutes=30), clock=clock)
    status = await ops.collect_status(clock.now, settings)
    assert status.degraded is False
    assert status.to_json()["webhooks"]["retrying"] == 1

    await _webhook(db_session, state="queued", next_attempt_in=-timedelta(hours=1), clock=clock)
    status = await ops.collect_status(clock.now, settings)
    assert _codes(status) == {"webhook_backlog_stale"}


async def test_failed_deliveries_over_threshold_are_degraded(
    settings: Settings, clock: Clock, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _healthy_worker(settings, clock)
    monkeypatch.setattr(settings, "ops_webhook_failed_max", 0)
    delivery = await _webhook(db_session, state="failed", next_attempt_in=timedelta(0), clock=clock)
    await db_session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.id == delivery.id)
        .values(updated_at=clock.now - timedelta(minutes=5))
    )
    user = await factories.create_user(db_session)
    for _ in range(settings.ops_notification_failed_max + 1):
        await factories.create_notification(db_session, user, state="failed")
    await db_session.execute(
        update(Notification).values(created_at=clock.now - timedelta(minutes=5))
    )
    await db_session.commit()

    status = await ops.collect_status(clock.now, settings)

    assert _codes(status) == {"webhook_failed", "notification_failed"}
    body = status.to_json()
    assert body["webhooks"]["failed"] == 1
    assert body["notifications"]["failed"] == settings.ops_notification_failed_max + 1


async def test_old_failure_outside_window_is_not_degraded(
    settings: Settings, clock: Clock, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _healthy_worker(settings, clock)
    monkeypatch.setattr(settings, "ops_webhook_failed_max", 0)
    delivery = await _webhook(db_session, state="failed", next_attempt_in=timedelta(0), clock=clock)
    await db_session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.id == delivery.id)
        .values(updated_at=clock.now - timedelta(days=2))
    )
    await db_session.commit()

    status = await ops.collect_status(clock.now, settings)

    assert status.degraded is False
    assert status.to_json()["webhooks"]["failed"] == 1


async def test_failed_max_update_is_degraded(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    db_session.add(
        MaxUpdate(
            max_update_id="u-1",
            update_type="message_created",
            raw_payload={},
            received_at=clock.now - timedelta(minutes=1),
            processing_error="RuntimeError",
            **({"status": "dead"} if hasattr(MaxUpdate, "status") else {}),
        )
    )
    await db_session.commit()

    status = await ops.collect_status(clock.now, settings)

    assert "max_updates_failed" in _codes(status)
    body = status.to_json()["max_updates"]
    assert body["dead_recent"] == 1
    assert body["by_state"][("dead" if hasattr(MaxUpdate, "status") else "failed")] == 1


async def test_stale_loop_and_failing_subscription_are_degraded(
    settings: Settings, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_updates_mode", "webhook")
    writer = ops.HeartbeatWriter.for_loops(
        {"notification_dispatcher": 1.0, "bot_subscription": 900.0}, settings
    )
    await writer.register(clock.now)
    clock.advance(120)
    await writer.failed("bot_subscription", clock.now, ConnectionError())

    status = await ops.collect_status(clock.now, settings)

    assert _codes(status) == {"worker_loop_stale", "max_subscription_failing"}
    body = status.to_json()
    assert body["max_subscription"] == {
        "mode": "webhook",
        "checked": True,
        "last_checked_at": None,
        "last_error_at": clock.now.isoformat(),
        "last_error": "ConnectionError",
        "failing": True,
    }


async def test_no_heartbeats_at_all_is_degraded(settings: Settings, clock: Clock) -> None:
    status = await ops.collect_status(clock.now, settings)
    assert _codes(status) == {"worker_heartbeat_missing"}


async def test_monitor_logs_alarm_with_machine_code(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    await _old_notification(db_session, timedelta(hours=1), clock)

    with structlog.testing.capture_logs() as logs:
        alarms = await ops_monitor.run_once(clock.now)

    assert alarms == 1
    [entry] = [e for e in logs if e["event"] == "ops_alarm"]
    assert entry["log_level"] == "error"
    assert entry["code"] == "notification_backlog_stale"


@pytest_asyncio.fixture
async def app_with_token(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> AsyncIterator[None]:
    monkeypatch.setattr(settings, "ops_token", OPS_TOKEN)
    yield


async def _get(path: str, client: tuple[str, int], headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=create_app(), client=client)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        return await http.get(path, headers=headers or {})


@pytest.mark.usefixtures("app_with_token")
async def test_ops_status_hidden_from_outside_without_token() -> None:
    response = await _get("/ops/status", EXTERNAL)
    assert response.status_code == 404
    assert "heartbeats" not in response.text

    wrong = await _get("/ops/status", EXTERNAL, {"X-Ops-Token": "guess"})
    assert wrong.status_code == 404
    metrics = await _get("/ops/metrics", EXTERNAL)
    assert metrics.status_code == 404


@pytest.mark.usefixtures("app_with_token")
async def test_ops_status_with_token_from_outside(settings: Settings, clock: Clock) -> None:
    await _healthy_worker(settings, clock)

    by_header = await _get("/ops/status", EXTERNAL, {"X-Ops-Token": OPS_TOKEN})
    by_bearer = await _get("/ops/status", EXTERNAL, {"Authorization": f"Bearer {OPS_TOKEN}"})

    assert by_header.status_code == 200
    assert by_bearer.status_code == 200
    body = by_header.json()
    assert body["degraded"] is False
    assert set(body) >= {
        "heartbeats",
        "notifications",
        "webhooks",
        "max_updates",
        "max_subscription",
    }
    assert by_header.headers["cache-control"] == "no-store"


async def test_ops_status_from_internal_network_without_token(
    settings: Settings, clock: Clock
) -> None:
    response = await _get("/ops/status", INTERNAL)
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["reasons"][0]["code"] == "worker_heartbeat_missing"


async def test_ops_status_closed_outside_when_token_not_configured() -> None:
    assert (await _get("/ops/status", EXTERNAL)).status_code == 404
    assert (await _get("/ops/status", EXTERNAL, {"X-Ops-Token": ""})).status_code == 404


async def test_ops_metrics_prometheus_text(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    await _healthy_worker(settings, clock)
    await _old_notification(db_session, timedelta(hours=1), clock)

    response = await _get("/ops/metrics", INTERNAL)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "repair_hub_ops_degraded 1" in text
    assert 'repair_hub_ops_alarm{code="notification_backlog_stale"} 1' in text
    assert 'repair_hub_notifications{state="queued"} 1' in text
    assert 'repair_hub_worker_loop_stale{loop="notification_dispatcher"} 0' in text


async def test_readyz_ignores_delivery_state(settings: Settings, clock: Clock) -> None:
    response = await _get("/readyz", EXTERNAL)
    assert response.status_code == 200


def test_invalid_ops_networks_fail_on_startup(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(settings, "ops_allowed_networks", "10.0.0.0/8,not-a-network")
    with pytest.raises(ValueError, match="OPS_ALLOWED_NETWORKS"):
        create_app()


def test_caddy_closes_ops_from_outside() -> None:
    caddyfile = (REPO_DIR / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    site = caddyfile[caddyfile.index("{$SITE_ADDRESS") :]
    api_matcher = next(line for line in site.splitlines() if line.strip().startswith("@api "))
    assert "/ops" not in api_matcher
    assert site.index("handle /ops/*") < site.index("try_files")
    block = site[site.index("handle /ops/*") :].split("}", 1)[0]
    assert "respond 404" in block
