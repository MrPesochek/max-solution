from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from connector import db, repo
from connector.onec_client import OneCUnreachableError
from connector.services import recovery, sync
from emulator import store
from emulator.metadata import ORDER
from tests.fake_platform import make_envelope


def _flaky_update(harness: Any, monkeypatch: Any, failures: int) -> dict[str, int]:
    original = harness.state.onec.update
    calls = {"n": 0}

    async def flaky(entity: str, ref_key: str, body: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise OneCUnreachableError("сервер 1С недоступен")
        return await original(entity, ref_key, body)

    monkeypatch.setattr(harness.state.onec, "update", flaky)
    return calls


def _event(harness: Any, event_id: str) -> sqlite3.Row:
    row = harness.state.conn.execute(
        "SELECT * FROM processed_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    assert row is not None
    return row


def _make_due(harness: Any, event_id: str) -> None:
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    harness.state.conn.execute(
        "UPDATE processed_events SET next_retry_at = ? WHERE event_id = ?", (past, event_id)
    )
    harness.state.conn.commit()


async def _linked_request(harness: Any, request_id: str) -> int:
    harness.subscribe()
    harness.platform.add_request(request_id)
    await harness.deliver("request.assigned", request_id)
    link = repo.get_link(harness.state.conn, request_id)
    current = int(harness.platform.requests[request_id]["version"])
    assert link is not None and link["applied_version"] == current
    return current


async def test_update_failure_is_reapplied_by_background_retry(harness, monkeypatch) -> None:
    applied = await _linked_request(harness, "req_upd")
    harness.platform.bump("req_upd", symptom_description="Течёт конденсат")
    calls = _flaky_update(harness, monkeypatch, failures=1)

    await harness.deliver("request.changed", "req_upd", event_id="evt_upd_v2")

    assert calls["n"] >= 2
    assert harness.prop("req_upd", "Неисправность").startswith("Течёт конденсат")
    link = repo.get_link(harness.state.conn, "req_upd")
    assert link is not None and link["applied_version"] == applied + 1
    assert _event(harness, "evt_upd_v2")["status"] == "processed"


async def test_failed_update_does_not_mark_version_applied(harness, monkeypatch) -> None:
    applied = await _linked_request(harness, "req_keep")
    harness.platform.bump("req_keep", symptom_description="Шумит компрессор")
    _flaky_update(harness, monkeypatch, failures=100)

    await harness.deliver("request.changed", "req_keep", event_id="evt_keep_v2")

    link = repo.get_link(harness.state.conn, "req_keep")
    assert link is not None and link["applied_version"] == applied
    assert not harness.prop("req_keep", "Неисправность").startswith("Шумит компрессор")
    assert _event(harness, "evt_keep_v2")["status"] == "failed"


async def test_full_reconciliation_reapplies_unapplied_version(harness, monkeypatch) -> None:
    applied = await _linked_request(harness, "req_full")
    harness.platform.bump("req_full", symptom_description="Не включается")
    _flaky_update(harness, monkeypatch, failures=3)
    await harness.deliver("request.changed", "req_full", event_id="evt_full_v2")
    assert not harness.prop("req_full", "Неисправность").startswith("Не включается")

    repo.set_cursor(harness.state.conn, "999")
    harness.platform.cursor_expired = True
    result = await sync.reconcile(harness.state)

    assert result.mode == "full"
    assert result.applied == 1
    assert harness.prop("req_full", "Неисправность").startswith("Не включается")
    link = repo.get_link(harness.state.conn, "req_full")
    assert link is not None and link["applied_version"] == applied + 1

    again = await sync.reconcile(harness.state)
    assert again.applied == 0


async def test_old_event_still_skipped_after_apply(harness) -> None:
    await _linked_request(harness, "req_old")
    reads_before = harness.platform.count("get_request")

    await harness.deliver("request.changed", "req_old", version=1, event_id="evt_old_v1")

    assert harness.platform.count("get_request") == reads_before
    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1


async def test_failure_after_document_created_is_finished_on_retry(harness, monkeypatch) -> None:
    harness.subscribe()
    harness.platform.add_request("req_new")
    _flaky_update(harness, monkeypatch, failures=1)

    await harness.deliver("request.assigned", "req_new")

    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1
    link = repo.get_link(harness.state.conn, "req_new")
    current = harness.platform.requests["req_new"]["version"]
    assert link is not None and link["applied_version"] == current


async def test_failed_event_retried_after_backoff(harness, monkeypatch) -> None:
    await _linked_request(harness, "req_bo")
    harness.platform.bump("req_bo", symptom_description="Иней на испарителе")
    calls = _flaky_update(harness, monkeypatch, failures=3)

    await harness.deliver("request.changed", "req_bo", event_id="evt_bo")

    row = _event(harness, "evt_bo")
    assert row["status"] == "failed" and row["attempts"] == 1
    next_retry = datetime.fromisoformat(row["next_retry_at"])
    assert next_retry > datetime.now(UTC) + timedelta(seconds=50)

    assert recovery.resume_unprocessed(harness.state) == 0
    assert calls["n"] == 3

    _make_due(harness, "evt_bo")
    assert recovery.resume_unprocessed(harness.state) == 1
    await harness.drain()

    assert harness.prop("req_bo", "Неисправность").startswith("Иней на испарителе")
    row = _event(harness, "evt_bo")
    assert row["status"] == "processed" and row["next_retry_at"] is None
    assert recovery.resume_unprocessed(harness.state) == 0


async def test_backoff_grows_and_event_becomes_dead(harness, monkeypatch) -> None:
    harness.state.settings.event_retry_max_rounds = 3
    await _linked_request(harness, "req_dead")
    harness.platform.bump("req_dead", symptom_description="Не запускается")
    _flaky_update(harness, monkeypatch, failures=1000)

    await harness.deliver("request.changed", "req_dead", event_id="evt_dead")
    first = _event(harness, "evt_dead")
    first_delay = datetime.fromisoformat(first["next_retry_at"]) - datetime.fromisoformat(
        first["processed_at"]
    )

    _make_due(harness, "evt_dead")
    assert recovery.resume_unprocessed(harness.state) == 1
    await harness.drain()
    second = _event(harness, "evt_dead")
    assert second["status"] == "failed" and second["attempts"] == 2
    second_delay = datetime.fromisoformat(second["next_retry_at"]) - datetime.fromisoformat(
        second["processed_at"]
    )
    assert second_delay > first_delay

    _make_due(harness, "evt_dead")
    assert recovery.resume_unprocessed(harness.state) == 1
    await harness.drain()
    dead = _event(harness, "evt_dead")
    assert dead["status"] == "dead" and dead["attempts"] == 3
    assert dead["next_retry_at"] is None

    assert recovery.resume_unprocessed(harness.state) == 0
    status = (await harness.client.get("/status")).json()
    assert status["dead_events"] == 1 and status["failed_events"] == 0


async def test_backoff_delay_is_capped(harness) -> None:
    conn = harness.state.conn
    repo.reserve_event(
        conn,
        event_id="evt_cap",
        delivery_id=None,
        event_type="request.changed",
        resource_id="req_cap",
        resource_version=1,
        payload={},
    )
    for _ in range(5):
        repo.mark_event_failed(
            conn,
            event_id="evt_cap",
            error="нет связи",
            max_attempts=10,
            base_delay_seconds=60,
            max_delay_seconds=300,
        )
    row = _event(harness, "evt_cap")
    delay = datetime.fromisoformat(row["next_retry_at"]) - datetime.fromisoformat(
        row["processed_at"]
    )
    assert delay == timedelta(seconds=300)


def _feed_event(harness: Any, request_id: str, event_id: str, symptom: str) -> None:
    card = harness.platform.bump(request_id, symptom_description=symptom)
    harness.platform.events.append(
        make_envelope(
            event_id=event_id,
            event_type="request.changed",
            resource_id=request_id,
            resource_version=card["version"],
        )
    )


async def test_events_feed_retries_due_failed_event(harness, monkeypatch) -> None:
    await _linked_request(harness, "req_feed")
    _feed_event(harness, "req_feed", "evt_feed", "Мигает дисплей")
    _flaky_update(harness, monkeypatch, failures=1)

    first = await sync.reconcile(harness.state)
    assert first.applied == 0
    assert _event(harness, "evt_feed")["status"] == "failed"
    assert repo.get_cursor(harness.state.conn) is None

    _make_due(harness, "evt_feed")
    second = await sync.reconcile(harness.state)
    assert second.applied == 1 and second.skipped_duplicates == 0
    assert harness.prop("req_feed", "Неисправность").startswith("Мигает дисплей")
    assert _event(harness, "evt_feed")["status"] == "processed"
    assert repo.get_cursor(harness.state.conn) is not None


async def test_events_feed_skips_not_due_failed_event(harness, monkeypatch) -> None:
    await _linked_request(harness, "req_skip")
    _feed_event(harness, "req_skip", "evt_skip", "Гудит вентилятор")
    calls = _flaky_update(harness, monkeypatch, failures=1)
    await sync.reconcile(harness.state)
    assert _event(harness, "evt_skip")["status"] == "failed"

    second = await sync.reconcile(harness.state)
    assert second.applied == 0 and second.skipped_duplicates == 1
    assert calls["n"] == 1
    assert repo.get_cursor(harness.state.conn) is not None

    _make_due(harness, "evt_skip")
    assert await recovery.recover_once(harness.state) == 1
    await harness.drain()
    assert harness.prop("req_skip", "Неисправность").startswith("Гудит вентилятор")
    assert _event(harness, "evt_skip")["status"] == "processed"


async def test_webhook_redelivery_of_due_failed_event_is_processed(harness, monkeypatch) -> None:
    await _linked_request(harness, "req_redeliver")
    harness.platform.bump("req_redeliver", symptom_description="Не держит температуру")
    _flaky_update(harness, monkeypatch, failures=3)
    await harness.deliver("request.changed", "req_redeliver", event_id="evt_re")
    assert _event(harness, "evt_re")["status"] == "failed"

    await harness.deliver("request.changed", "req_redeliver", event_id="evt_re")
    assert _event(harness, "evt_re")["status"] == "failed"
    _make_due(harness, "evt_re")
    await harness.deliver("request.changed", "req_redeliver", event_id="evt_re")

    assert _event(harness, "evt_re")["status"] == "processed"
    assert harness.prop("req_redeliver", "Неисправность").startswith("Не держит температуру")
    outcomes = [row["outcome"] for row in repo.recent_deliveries(harness.state.conn)]
    assert outcomes[:2] == ["retry", "duplicate"]


def test_old_database_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(str(path))
    old.executescript(
        """
        CREATE TABLE links (
            request_id TEXT PRIMARY KEY, ref_key TEXT NOT NULL UNIQUE, doc_number TEXT,
            platform_version INTEGER NOT NULL, card_json TEXT NOT NULL, data_version TEXT,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE processed_events (
            event_id TEXT PRIMARY KEY, delivery_id TEXT, type TEXT NOT NULL,
            resource_id TEXT NOT NULL, resource_version INTEGER, received_at TEXT NOT NULL,
            processed_at TEXT, status TEXT NOT NULL DEFAULT 'received', error TEXT,
            payload_json TEXT NOT NULL
        );
        INSERT INTO links VALUES ('r_active', 'k1', '1', 5, '{}', NULL, 1, 't', 't');
        INSERT INTO links VALUES ('r_closed', 'k2', '2', 7, '{}', NULL, 0, 't', 't');
        INSERT INTO processed_events (event_id, type, resource_id, received_at, status,
            payload_json) VALUES ('e1', 'request.changed', 'r_active', 't', 'failed', '{}');
        """
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    active = repo.get_link(conn, "r_active")
    closed = repo.get_link(conn, "r_closed")
    assert active is not None and active["applied_version"] == 0
    assert closed is not None and closed["applied_version"] == 7
    assert len(repo.list_unprocessed_events(conn)) == 1
    conn.close()

    db.connect(path).close()
