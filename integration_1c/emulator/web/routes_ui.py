from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from emulator import store
from emulator.metadata import (
    COUNTERPARTIES,
    EDITABLE_PROPERTIES,
    EMPTY_DATE,
    EMPTY_REF,
    FILES,
    ITEMS,
    ORDER,
    PROPERTIES,
    STATES,
)
from emulator.money import minor_to_rub, rub_to_minor
from emulator.state import EmulatorState
from emulator.web.auth import require_session
from emulator.web.templating import templates

CANCELLATION_PENDING_LABEL = "заказчик просит отменить"

router = APIRouter(dependencies=[Depends(require_session)])

_BLANK_ROWS = 3
_MAX_ROWS = 50


def _conn(request: Request) -> sqlite3.Connection:
    state: EmulatorState = request.app.state.emulator
    return state.conn


def _names(conn: sqlite3.Connection, entity: str) -> dict[str, str]:
    return {str(o["Ref_Key"]): str(o.get("Description", "")) for o in store.list_all(conn, entity)}


def _props(conn: sqlite3.Connection, doc: dict[str, Any]) -> dict[str, str]:
    names = _names(conn, PROPERTIES)
    result: dict[str, str] = {}
    for row in doc.get("ДополнительныеРеквизиты") or []:
        name = names.get(str(row.get("Свойство_Key")))
        if name:
            result[name] = str(row.get("ТекстоваяСтрока") or row.get("Значение") or "")
    return result


@router.get("/ui/orders")
async def orders_list(request: Request) -> Response:
    conn = _conn(request)
    counterparties = _names(conn, COUNTERPARTIES)
    states = _names(conn, STATES)
    orders = []
    for doc in reversed(store.list_all(conn, ORDER)):
        orders.append(
            {
                "doc": doc,
                "counterparty": counterparties.get(str(doc.get("Контрагент_Key")), "—"),
                "state": states.get(str(doc.get("СостояниеЗаказа_Key")), "—"),
                "platform": _props(conn, doc).get("Заявка платформы", ""),
            }
        )
    return templates.TemplateResponse(request, "orders_list.html", {"orders": orders})


def _get_order(conn: sqlite3.Connection, ref_key: str) -> dict[str, Any]:
    try:
        doc = store.get(conn, ORDER, ref_key)
    except store.StoreError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    if doc is None:
        raise HTTPException(status_code=404, detail="документ не найден")
    return doc


@router.get("/ui/orders/{ref_key}")
async def order_form(
    request: Request, ref_key: str, message: str | None = None, error: int = 0
) -> Response:
    conn = _conn(request)
    doc = _get_order(conn, ref_key)
    props = _props(conn, doc)
    rows = [
        {**row, "amount_text": minor_to_rub(rub_to_minor(str(row.get("Сумма") or "")))}
        for row in doc.get("Работы") or []
    ]
    rows += [
        {"Номенклатура_Key": "", "Содержание": "", "amount_text": ""} for _ in range(_BLANK_ROWS)
    ]
    files = [f for f in store.list_all(conn, FILES) if f.get("ВладелецФайла_Key") == ref_key]
    platform_props = [
        (name, value) for name, value in props.items() if name not in EDITABLE_PROPERTIES
    ]
    return templates.TemplateResponse(
        request,
        "order_form.html",
        {
            "doc": doc,
            "counterparty": _names(conn, COUNTERPARTIES).get(str(doc.get("Контрагент_Key")), "—"),
            "states": store.list_all(conn, STATES),
            "items": store.list_all(conn, ITEMS),
            "rows": rows,
            "props": props,
            "editable": EDITABLE_PROPERTIES,
            "platform_props": platform_props,
            "files": files,
            "cancellation_requested": props.get("Статус на платформе")
            == CANCELLATION_PENDING_LABEL,
            "message": message,
            "error": bool(error),
        },
    )


def _local_datetime(value: str) -> str:
    text = value.strip()
    if not text:
        return EMPTY_DATE
    if len(text) == 16:
        text += ":00"
    return text[:19]


def _amount(value: str) -> int | float:
    minor = rub_to_minor(value) or 0
    return minor // 100 if minor % 100 == 0 else minor / 100


def _changes(conn: sqlite3.Connection, doc: dict[str, Any], form: dict[str, str]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if "state" in form:
        by_name = {v: k for k, v in _names(conn, STATES).items()}
        if form["state"] not in by_name:
            raise ValueError(f"нет состояния «{form['state']}»")
        changes["СостояниеЗаказа_Key"] = by_name[form["state"]]
    if "start" in form:
        changes["Начало"] = _local_datetime(form["start"])
    if "end" in form:
        changes["Окончание"] = _local_datetime(form["end"])
    if "comment" in form:
        changes["Комментарий"] = form["comment"]

    prop_values = {k[len("prop:") :]: v for k, v in form.items() if k.startswith("prop:")}
    if prop_values:
        keys = {v: k for k, v in _names(conn, PROPERTIES).items()}
        rows = [dict(r) for r in doc.get("ДополнительныеРеквизиты") or []]
        for name, value in prop_values.items():
            key = keys.get(name)
            if key is None:
                continue
            row = next((r for r in rows if r.get("Свойство_Key") == key), None)
            if row is None:
                if value.strip():
                    rows.append(
                        {
                            "Свойство_Key": key,
                            "Значение": value.strip(),
                            "Значение_Type": "Edm.String",
                        }
                    )
            else:
                row["Значение"] = value.strip()
                row["ТекстоваяСтрока"] = ""
        changes["ДополнительныеРеквизиты"] = [
            {k: v for k, v in r.items() if k != "LineNumber"} for r in rows
        ]

    if any(k.startswith("row-") for k in form):
        works = []
        for index in range(_MAX_ROWS):
            item = form.get(f"row-{index}-item", "").strip()
            content = form.get(f"row-{index}-content", "").strip()
            amount = form.get(f"row-{index}-amount", "").strip()
            if not (item or content or amount):
                continue
            total = _amount(amount)
            works.append(
                {
                    "Номенклатура_Key": item or EMPTY_REF,
                    "Содержание": content,
                    "Количество": 1,
                    "Цена": total,
                    "Сумма": total,
                }
            )
        changes["Работы"] = works
    return changes


@router.post("/ui/orders/{ref_key}")
async def order_submit(request: Request, ref_key: str) -> Response:
    conn = _conn(request)
    doc = _get_order(conn, ref_key)
    raw = await request.form()
    form = {k: v for k, v in raw.items() if isinstance(v, str) and k != "csrf_token"}
    action = form.pop("action", "write")
    try:
        changes = _changes(conn, doc, form)
        if changes:
            store.update(conn, ORDER, ref_key, changes)
        if action == "post":
            store.set_posted(conn, ORDER, ref_key, True)
            message = "Документ проведён"
        elif action == "unpost":
            store.set_posted(conn, ORDER, ref_key, False)
            message = "Проведение отменено"
        else:
            message = "Документ записан"
        error = 0
    except (ValueError, store.StoreError) as exc:
        message = f"Не удалось: {getattr(exc, 'message', str(exc))}"
        error = 1
    return RedirectResponse(
        f"/ui/orders/{ref_key}?message={quote(message)}&error={error}", status_code=303
    )


@router.get("/ui/files/{ref_key}")
async def file_download(request: Request, ref_key: str) -> Response:
    conn = _conn(request)
    item = store.get(conn, FILES, ref_key)
    content = store.file_content(conn, ref_key) if item else None
    if item is None or content is None:
        raise HTTPException(status_code=404, detail="файл не найден")
    extension = str(item.get("Расширение") or "bin")
    media = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        extension, "application/octet-stream"
    )
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename=file.{extension}"},
    )
