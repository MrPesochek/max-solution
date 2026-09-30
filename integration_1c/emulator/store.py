from __future__ import annotations

import base64
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from emulator.metadata import (
    BINARY,
    EMPTY_DATE,
    EMPTY_REF,
    ENTITIES,
    ITEMS,
    ORDER,
    PROPERTIES,
    SEED_ITEMS,
    SEED_PROPERTIES,
    SEED_STATES,
    STATES,
    EntityDef,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    entity TEXT NOT NULL,
    ref_key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (entity, ref_key)
);
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


class StoreError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def connect(path: Path | None) -> sqlite3.Connection:
    if path is None:
        conn = sqlite3.connect(":memory:", check_same_thread=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=True)
        conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def entity_def(entity: str) -> EntityDef:
    definition = ENTITIES.get(entity)
    if definition is None:
        raise StoreError(f"Не найден объект метаданных «{entity}»", status_code=404)
    return definition


def _next(conn: sqlite3.Connection, name: str) -> int:
    conn.execute(
        """INSERT INTO counters (name, value) VALUES (?, 1)
           ON CONFLICT(name) DO UPDATE SET value = value + 1""",
        (name,),
    )
    row = conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
    return int(row["value"])


def _data_version(conn: sqlite3.Connection) -> str:
    return base64.b64encode(_next(conn, "data_version").to_bytes(8, "big")).decode()


def _normalize(definition: EntityDef, body: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    allowed = definition.all_fields()
    result: dict[str, Any] = {}
    for key, value in body.items():
        if key.startswith("odata.") or "@" in key:
            continue
        if key in definition.tables:
            result[key] = _normalize_rows(definition, key, value)
            continue
        if key in {"Ref_Key", "DataVersion", "Posted"} and definition.kind != "register":
            continue
        if key not in allowed:
            raise StoreError(f"Неизвестное свойство «{key}» объекта {definition.name}")
        result[key] = value
    if not partial:
        for key, default in allowed.items():
            result.setdefault(key, default)
        for table in definition.tables:
            result.setdefault(table, [])
    return result


def _normalize_rows(definition: EntityDef, table: str, rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise StoreError(f"Табличная часть «{table}» должна быть массивом")
    columns = definition.tables[table]
    normalized = []
    for number, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise StoreError(f"Строка табличной части «{table}» должна быть объектом")
        unknown = set(raw) - set(columns)
        if unknown:
            raise StoreError(f"Неизвестное свойство «{sorted(unknown)[0]}» табличной части {table}")
        row = {**columns, **raw, "LineNumber": str(number)}
        normalized.append(row)
    return normalized


def _recalculate(definition: EntityDef, data: dict[str, Any]) -> None:
    if definition.name == ORDER:
        total = sum(float(r.get("Сумма") or 0) for r in data.get("Работы", []))
        data["СуммаДокумента"] = int(total) if total.is_integer() else round(total, 2)


def _save(
    conn: sqlite3.Connection, entity: str, ref_key: str, seq: int, data: dict[str, Any]
) -> None:
    conn.execute(
        """INSERT INTO objects (entity, ref_key, seq, data_json) VALUES (?, ?, ?, ?)
           ON CONFLICT(entity, ref_key) DO UPDATE SET data_json = excluded.data_json""",
        (entity, ref_key, seq, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()


def create(conn: sqlite3.Connection, entity: str, body: dict[str, Any]) -> dict[str, Any]:
    definition = entity_def(entity)
    data = _normalize(definition, body, partial=False)
    ref_key = str(uuid.uuid4())
    seq = _next(conn, f"seq:{entity}")
    if definition.kind != "register":
        data["Ref_Key"] = ref_key
        data["DataVersion"] = _data_version(conn)
    if definition.kind == "document":
        if not data.get("Number"):
            data["Number"] = f"{definition.number_prefix}{seq:06d}"
        if not data.get("Date") or data["Date"] == EMPTY_DATE:
            data["Date"] = datetime.now().replace(microsecond=0).isoformat()
        data["Posted"] = False
    elif definition.kind in {"catalog", "chart"} and not data.get("Code"):
        data["Code"] = f"{seq:09d}"
    _recalculate(definition, data)
    _save(conn, entity, ref_key, seq, data)
    return data


def get(conn: sqlite3.Connection, entity: str, ref_key: str) -> dict[str, Any] | None:
    entity_def(entity)
    row = conn.execute(
        "SELECT data_json FROM objects WHERE entity = ? AND ref_key = ?", (entity, ref_key.lower())
    ).fetchone()
    return cast(dict[str, Any], json.loads(row["data_json"])) if row else None


def list_all(conn: sqlite3.Connection, entity: str) -> list[dict[str, Any]]:
    entity_def(entity)
    rows = conn.execute(
        "SELECT data_json FROM objects WHERE entity = ? ORDER BY seq", (entity,)
    ).fetchall()
    return [cast(dict[str, Any], json.loads(r["data_json"])) for r in rows]


def update(
    conn: sqlite3.Connection, entity: str, ref_key: str, body: dict[str, Any]
) -> dict[str, Any]:
    definition = entity_def(entity)
    if definition.kind == "register":
        raise StoreError("Изменение записей регистра по ключу не поддерживается")
    current = get(conn, entity, ref_key)
    if current is None:
        raise StoreError("Объект не найден", status_code=404)
    changes = _normalize(definition, body, partial=True)
    current.update(changes)
    current["DataVersion"] = _data_version(conn)
    _recalculate(definition, current)
    _save(conn, entity, ref_key.lower(), 0, current)
    return current


def set_posted(conn: sqlite3.Connection, entity: str, ref_key: str, posted: bool) -> dict[str, Any]:
    definition = entity_def(entity)
    if definition.kind != "document":
        raise StoreError("Проведение доступно только для документов")
    current = get(conn, entity, ref_key)
    if current is None:
        raise StoreError("Объект не найден", status_code=404)
    if posted:
        if current.get("DeletionMark"):
            raise StoreError(
                "Помеченный на удаление документ не может быть проведен", status_code=500
            )
        if current.get("Контрагент_Key", EMPTY_REF) == EMPTY_REF:
            raise StoreError("Поле «Контрагент» не заполнено", status_code=500)
    current["Posted"] = posted
    current["DataVersion"] = _data_version(conn)
    _save(conn, entity, ref_key.lower(), 0, current)
    return current


def file_content(conn: sqlite3.Connection, file_ref: str) -> bytes | None:
    for record in list_all(conn, BINARY):
        if str(record.get("Файл", "")).lower() == file_ref.lower():
            return base64.b64decode(str(record.get("ДвоичныеДанныеФайла_Base64Data") or ""))
    return None


def seed(conn: sqlite3.Connection) -> None:
    states = {s["Description"] for s in list_all(conn, STATES)}
    for name in SEED_STATES:
        if name not in states:
            create(conn, STATES, {"Description": name})
    if not list_all(conn, ITEMS):
        for name, kind in SEED_ITEMS:
            create(conn, ITEMS, {"Description": name, "ТипНоменклатуры": kind})
    existing = {p["Description"] for p in list_all(conn, PROPERTIES)}
    for name in SEED_PROPERTIES:
        if name not in existing:
            create(conn, PROPERTIES, {"Description": name, "Заголовок": name})
