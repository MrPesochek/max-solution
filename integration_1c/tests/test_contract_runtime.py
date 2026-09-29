from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from connector import db, repo
from connector.contract import REQUEST_EVENTS, SUBSCRIBED_EVENTS, WebhookEventType
from connector.platform_client import PlatformContractError
from connector.services import inbound
from connector.services.bootstrap import ensure_subscription, subscribed_events
from connector.settings import Settings
from tests.conftest import SECRET


def test_subscription_covers_every_routed_event() -> None:
    assert set(subscribed_events()) == SUBSCRIBED_EVENTS
    assert REQUEST_EVENTS <= SUBSCRIBED_EVENTS
    assert "offer.selected" in SUBSCRIBED_EVENTS
    assert "assignment.revoked" in SUBSCRIBED_EVENTS
    assert set(get_args(WebhookEventType)) >= SUBSCRIBED_EVENTS
    assert "ping" not in SUBSCRIBED_EVENTS


async def test_offer_selected_creates_document(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_offer")
    await harness.deliver("offer.selected", "req_offer")
    assert repo.get_link(harness.state.conn, "req_offer") is not None


async def test_stale_subscription_is_recreated(harness) -> None:
    harness.platform.subscription = {
        "id": "whs_old",
        "url": "http://connector.test/webhooks/platform",
        "secret": "old-secret",
        "status": "active",
        "events": ["request.assigned", "request.changed"],
    }
    repo.save_subscription(
        harness.state.conn,
        subscription_id="whs_old",
        secret="old-secret",
        url="http://connector.test/webhooks/platform",
        status="active",
    )

    assert await ensure_subscription(harness.state) is True

    assert harness.platform.count("create_subscription") == 1
    assert set(harness.platform.subscription["events"]) == SUBSCRIBED_EVENTS
    assert harness.platform.deleted_subscriptions == ["whs_old"]
    saved = repo.get_subscription(harness.state.conn)
    assert saved["subscription_id"] == harness.platform.subscription["id"]
    assert saved["secret"] == SECRET


async def test_current_subscription_is_kept(harness) -> None:
    assert await ensure_subscription(harness.state) is True
    assert await ensure_subscription(harness.state) is True
    assert harness.platform.count("create_subscription") == 1
    assert harness.platform.deleted_subscriptions == []


async def test_subscription_check_failure_keeps_subscription(harness) -> None:
    harness.subscribe()
    harness.platform.fail_list_subscriptions = True
    assert await ensure_subscription(harness.state) is True
    assert harness.platform.count("create_subscription") == 0


async def test_malformed_card_is_explicit_error(harness) -> None:
    harness.subscribe()
    card = harness.platform.add_request("req_bad")
    card["assignment"]["state"] = "unknown_state"
    card["versoin"] = card.pop("version")

    with pytest.raises(PlatformContractError) as exc:
        await harness.state.client.get_request("req_bad")
    assert "assignment.state: literal_error" in str(exc.value)
    assert "version" in str(exc.value)
    assert "Не морозит" not in str(exc.value)

    with pytest.raises(PlatformContractError):
        await inbound.handle_request(harness.state, "req_bad")
    assert repo.get_link(harness.state.conn, "req_bad") is None


async def test_former_assignment_card_passes(harness) -> None:
    card = harness.platform.add_request("req_former")
    card["assignment"]["state"] = "revoked"
    former = await harness.state.client.get_request("req_former")
    assert "status" not in former
    await inbound.handle_request(harness.state, "req_former")
    assert repo.get_link(harness.state.conn, "req_former") is None


async def test_card_with_new_fields_passes(harness) -> None:
    harness.platform.add_request("req_new", some_future_field={"x": 1})
    card = await harness.state.client.get_request("req_new")
    assert card["some_future_field"] == {"x": 1}


def test_new_database_has_current_schema_version(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "new.sqlite3")
    assert db.schema_version(conn) == db.SCHEMA_VERSION
    conn.close()
    again = db.connect(tmp_path / "new.sqlite3")
    assert db.schema_version(again) == db.SCHEMA_VERSION


def test_unversioned_database_gets_version(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(str(path))
    old.execute(
        "CREATE TABLE links (request_id TEXT PRIMARY KEY, ref_key TEXT NOT NULL UNIQUE, "
        "doc_number TEXT, platform_version INTEGER NOT NULL, card_json TEXT NOT NULL, "
        "data_version TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    old.commit()
    old.close()
    conn = db.connect(path)
    assert db.schema_version(conn) == db.SCHEMA_VERSION
    assert "applied_version" in {row[1] for row in conn.execute("PRAGMA table_info(links)")}


def test_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    future = sqlite3.connect(str(path))
    future.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    future.commit()
    future.close()
    with pytest.raises(RuntimeError, match="новее кода"):
        db.connect(path)


async def test_request_locks_are_released(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_lock")
    await harness.deliver("request.assigned", "req_lock")
    assert harness.state._locks == {}


async def test_request_lock_still_serializes(harness) -> None:
    order: list[str] = []

    async def worker(name: str) -> None:
        async with harness.state.lock_for("req_x"):
            order.append(f"{name}+")
            await asyncio.sleep(0.01)
            order.append(f"{name}-")

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert order == ["a+", "a-", "b+", "b-", "c+", "c-"]
    assert harness.state._locks == {}


def test_platform_key_over_http_refused() -> None:
    with pytest.raises(ValidationError, match="CONNECTOR_PLATFORM_API_BASE_URL"):
        Settings(platform_api_base_url="http://platform.example.com/api/v1")
    with pytest.raises(ValidationError):
        Settings(platform_api_base_url="ftp://platform.example.com/api/v1")


@pytest.mark.parametrize(
    "url",
    [
        "https://platform.example.com/api/v1",
        "http://localhost:8000/api/v1",
        "http://127.0.0.1:8000/api/v1",
        "http://api:8000/api/v1",
    ],
)
def test_platform_url_allowed(url: str) -> None:
    assert Settings(platform_api_base_url=url).platform_api_base_url == url


def test_platform_http_allowed_by_flag() -> None:
    settings = Settings(
        platform_api_base_url="http://platform.lan/api/v1", platform_allow_http=True
    )
    assert settings.platform_allow_http is True
