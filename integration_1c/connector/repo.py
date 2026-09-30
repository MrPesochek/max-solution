from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from connector.db import dumps


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_link(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM links WHERE request_id = ?", (request_id,)).fetchone()
    return cast("sqlite3.Row | None", row)


def get_link_by_ref(conn: sqlite3.Connection, ref_key: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM links WHERE ref_key = ?", (ref_key,)).fetchone()
    return cast("sqlite3.Row | None", row)


def link_card(row: sqlite3.Row) -> dict[str, Any]:
    return dict(json.loads(row["card_json"]))


def create_link(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    ref_key: str,
    doc_number: str | None,
    card: dict[str, Any],
    data_version: str | None,
) -> sqlite3.Row:
    now = _now()
    conn.execute(
        """INSERT INTO links (request_id, ref_key, doc_number, platform_version, card_json,
               data_version, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            request_id,
            ref_key,
            doc_number,
            int(card.get("version") or 0),
            dumps(card),
            data_version,
            now,
            now,
        ),
    )
    conn.commit()
    row = get_link(conn, request_id)
    if row is None:
        raise RuntimeError(f"связь заявки {request_id} с документом 1С не записалась")
    return row


def update_link_card(conn: sqlite3.Connection, request_id: str, card: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE links SET card_json = ?, platform_version = ?, updated_at = ?
           WHERE request_id = ? AND platform_version <= ?""",
        (
            dumps(card),
            int(card.get("version") or 0),
            _now(),
            request_id,
            int(card.get("version") or 0),
        ),
    )
    conn.commit()


def mark_link_applied(conn: sqlite3.Connection, request_id: str, version: int) -> None:
    conn.execute(
        """UPDATE links SET applied_version = ?, updated_at = ?
           WHERE request_id = ? AND applied_version < ?""",
        (version, _now(), request_id, version),
    )
    conn.commit()


def set_link_data_version(conn: sqlite3.Connection, request_id: str, data_version: str) -> None:
    conn.execute(
        "UPDATE links SET data_version = ?, updated_at = ? WHERE request_id = ?",
        (data_version, _now(), request_id),
    )
    conn.commit()


def deactivate_link(conn: sqlite3.Connection, request_id: str) -> None:
    conn.execute(
        "UPDATE links SET active = 0, updated_at = ? WHERE request_id = ?", (_now(), request_id)
    )
    conn.commit()


def list_active_links(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM links WHERE active = 1 ORDER BY created_at").fetchall()


def list_links(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM links ORDER BY updated_at DESC").fetchall()


FINAL_STATUSES = ("done", "rejected", "failed")


def find_action(
    conn: sqlite3.Connection, *, request_id: str, action: str, fingerprint: str
) -> sqlite3.Row | None:
    row = conn.execute(
        """SELECT * FROM outbound_actions
           WHERE request_id = ? AND action = ? AND fingerprint = ?
           ORDER BY id DESC LIMIT 1""",
        (request_id, action, fingerprint),
    ).fetchone()
    return cast("sqlite3.Row | None", row)


def create_action(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    ref_key: str,
    action: str,
    fingerprint: str,
    data_version: str,
    idempotency_key: str,
    body: dict[str, Any],
) -> sqlite3.Row:
    now = _now()
    cur = conn.execute(
        """INSERT INTO outbound_actions (request_id, ref_key, action, fingerprint, data_version,
               idempotency_key, body_json, status, attempts, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
        (
            request_id,
            ref_key,
            action,
            fingerprint,
            data_version,
            idempotency_key,
            dumps(body),
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM outbound_actions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return cast("sqlite3.Row", row)


def finish_action(
    conn: sqlite3.Connection, action_id: int, *, status: str, detail: str = ""
) -> None:
    conn.execute(
        """UPDATE outbound_actions SET status = ?, detail = ?, attempts = attempts + 1,
               updated_at = ? WHERE id = ?""",
        (status, detail[:2000], _now(), action_id),
    )
    conn.commit()


def list_actions(conn: sqlite3.Connection, request_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outbound_actions WHERE request_id = ? ORDER BY id", (request_id,)
    ).fetchall()


def attachment_uploaded(conn: sqlite3.Connection, attachment_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM uploaded_attachments WHERE attachment_id = ?", (attachment_id,)
    ).fetchone()
    return row is not None


def save_uploaded_attachment(
    conn: sqlite3.Connection,
    *,
    attachment_id: str,
    request_id: str,
    file_ref_key: str | None,
    size_bytes: int,
    content_type: str | None,
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO uploaded_attachments
               (attachment_id, request_id, file_ref_key, size_bytes, content_type, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (attachment_id, request_id, file_ref_key, size_bytes, content_type, _now()),
    )
    conn.commit()


def list_uploaded_attachments(conn: sqlite3.Connection, request_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM uploaded_attachments WHERE request_id = ? ORDER BY uploaded_at",
        (request_id,),
    ).fetchall()


RETRY_DUE = "retry"


def reserve_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    delivery_id: str | None,
    event_type: str,
    resource_id: str,
    resource_version: int | None,
    payload: dict[str, Any],
) -> bool:
    return (
        claim_event(
            conn,
            event_id=event_id,
            delivery_id=delivery_id,
            event_type=event_type,
            resource_id=resource_id,
            resource_version=resource_version,
            payload=payload,
        )
        == "new"
    )


def claim_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    delivery_id: str | None,
    event_type: str,
    resource_id: str,
    resource_version: int | None,
    payload: dict[str, Any],
) -> str:
    try:
        conn.execute(
            """INSERT INTO processed_events
               (event_id, delivery_id, type, resource_id, resource_version,
                received_at, status, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, 'received', ?)""",
            (
                event_id,
                delivery_id,
                event_type,
                resource_id,
                resource_version,
                _now(),
                dumps(payload),
            ),
        )
        conn.commit()
        return "new"
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT status, next_retry_at FROM processed_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is not None and _retry_due(row["status"], row["next_retry_at"]):
            return RETRY_DUE
        return "duplicate"


def _retry_due(status: str, next_retry_at: str | None) -> bool:
    return status == "failed" and (next_retry_at is None or next_retry_at <= _now())


def list_unprocessed_events(
    conn: sqlite3.Connection, *, received_before: datetime | None = None
) -> list[dict[str, Any]]:
    before = received_before.isoformat() if received_before is not None else None
    sql = """SELECT payload_json FROM processed_events
             WHERE (status = 'received' AND (? IS NULL OR received_at < ?))
                OR (status = 'failed' AND (next_retry_at IS NULL OR next_retry_at <= ?))
             ORDER BY received_at"""
    params = (before, before, _now())
    rows = conn.execute(sql, params).fetchall()
    return [cast(dict[str, Any], json.loads(row["payload_json"])) for row in rows]


def mark_event_processed(
    conn: sqlite3.Connection, *, event_id: str, status: str, error: str | None = None
) -> None:
    conn.execute(
        """UPDATE processed_events SET status = ?, processed_at = ?, error = ?,
               next_retry_at = NULL WHERE event_id = ?""",
        (status, _now(), error, event_id),
    )
    conn.commit()


def mark_event_failed(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    error: str,
    max_attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> str:
    row = conn.execute(
        "SELECT attempts FROM processed_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    attempts = (int(row["attempts"]) if row is not None else 0) + 1
    now = datetime.now(UTC)
    if attempts >= max(1, max_attempts):
        status, next_retry_at = "dead", None
    else:
        delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempts - 1)))
        status, next_retry_at = "failed", (now + timedelta(seconds=delay)).isoformat()
    conn.execute(
        """UPDATE processed_events SET status = ?, processed_at = ?, error = ?, attempts = ?,
               next_retry_at = ? WHERE event_id = ?""",
        (status, now.isoformat(), error[:2000], attempts, next_retry_at, event_id),
    )
    conn.commit()
    return status


def count_events(conn: sqlite3.Connection, status: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM processed_events WHERE status = ?", (status,)
    ).fetchone()
    return int(row["n"])


def log_delivery(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    delivery_id: str | None,
    event_type: str | None,
    signature_valid: bool,
    outcome: str,
) -> None:
    conn.execute(
        """INSERT INTO deliveries_log
           (event_id, delivery_id, event_type, received_at, signature_valid, outcome)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, delivery_id, event_type, _now(), int(signature_valid), outcome),
    )
    conn.commit()


def recent_deliveries(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM deliveries_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_subscription(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM webhook_subscription WHERE id = 1").fetchone()
    return cast("sqlite3.Row | None", row)


def save_subscription(
    conn: sqlite3.Connection, *, subscription_id: str, secret: str, url: str, status: str
) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO webhook_subscription (id, subscription_id, secret, url, status,
               created_at, updated_at)
           VALUES (1, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               subscription_id = excluded.subscription_id,
               secret = excluded.secret,
               url = excluded.url,
               status = excluded.status,
               updated_at = excluded.updated_at""",
        (subscription_id, secret, url, status, now, now),
    )
    conn.commit()


def update_subscription_status(conn: sqlite3.Connection, status: str) -> None:
    conn.execute(
        "UPDATE webhook_subscription SET status = ?, updated_at = ? WHERE id = 1",
        (status, _now()),
    )
    conn.commit()


def get_cursor(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT cursor FROM events_cursor WHERE id = 1").fetchone()
    return str(row["cursor"]) if row and row["cursor"] is not None else None


def set_cursor(conn: sqlite3.Connection, cursor: str | None) -> None:
    conn.execute(
        """INSERT INTO events_cursor (id, cursor, updated_at) VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               cursor = excluded.cursor, updated_at = excluded.updated_at""",
        (cursor, _now()),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings_kv WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row is not None else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO settings_kv (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()
