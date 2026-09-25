from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA = """
-- Сопоставление заявки платформы и документа 1С. Опрос 1С идёт только по активным строкам.
-- platform_version — последняя прочитанная версия карточки (card_json), applied_version —
-- версия, полностью перенесённая в документ 1С. Повтор события и сверка сравнивают
-- с applied_version: сбой записи в 1С посреди обновления не должен «съедать» версию.
CREATE TABLE IF NOT EXISTS links (
    request_id TEXT PRIMARY KEY,
    ref_key TEXT NOT NULL UNIQUE,
    doc_number TEXT,
    platform_version INTEGER NOT NULL,
    applied_version INTEGER NOT NULL DEFAULT 0,
    card_json TEXT NOT NULL,
    data_version TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Статусы: received -> processed | failed (повтор после next_retry_at) -> dead (попытки
-- исчерпаны). attempts — число неудачных раундов фоновой обработки.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    delivery_id TEXT,
    type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_version INTEGER,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    delivery_id TEXT,
    event_type TEXT,
    received_at TEXT NOT NULL,
    signature_valid INTEGER NOT NULL,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_subscription (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    subscription_id TEXT,
    secret TEXT,
    url TEXT,
    status TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS events_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cursor TEXT,
    updated_at TEXT
);

-- Журнал действий 1С -> платформа. Ключ идемпотентности сохраняется до вызова API,
-- поэтому повтор после сбоя идёт с тем же ключом и телом.
CREATE TABLE IF NOT EXISTS outbound_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    ref_key TEXT NOT NULL,
    action TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    data_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    body_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outbound_actions_lookup
    ON outbound_actions (request_id, action, fingerprint);

-- Вложения платформы, уже выгруженные в 1С (присоединённые файлы документа).
CREATE TABLE IF NOT EXISTS uploaded_attachments (
    attachment_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    file_ref_key TEXT,
    size_bytes INTEGER NOT NULL,
    content_type TEXT,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def connect_memory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _migration_1(conn: sqlite3.Connection) -> None:
    """Столбцы, появившиеся до учёта версии схемы: база без `user_version` могла
    быть создана любой из прежних версий, поэтому каждый столбец проверяется."""
    if "applied_version" not in _columns(conn, "links"):
        conn.execute("ALTER TABLE links ADD COLUMN applied_version INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE links SET applied_version = platform_version WHERE active = 0")
    events = _columns(conn, "processed_events")
    if "attempts" not in events:
        conn.execute("ALTER TABLE processed_events ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    if "next_retry_at" not in events:
        conn.execute("ALTER TABLE processed_events ADD COLUMN next_retry_at TEXT")


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_migration_1]
SCHEMA_VERSION = len(_MIGRATIONS)


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _migrate(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"база коннектора версии {current} новее кода (ожидается {SCHEMA_VERSION}): "
            "обновите коннектор или восстановите базу из копии"
        )
    for version in range(current, SCHEMA_VERSION):
        _MIGRATIONS[version](conn)
        conn.execute(f"PRAGMA user_version = {version + 1}")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
