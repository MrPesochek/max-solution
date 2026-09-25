from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from connector import repo
from connector.actions import PlannedAction, content_fingerprint, extract_view, plan_actions
from connector.onec_client import OneCError, OneCUnreachableError, guid_literal
from connector.onec_directory import ProfileMismatchError
from connector.platform_client import (
    PlatformApiError,
    PlatformUnreachableError,
    VersionConflictError,
)
from connector.services import documents
from connector.state import AppState

logger = logging.getLogger("onec_connector.outbound")

_MAX_STEPS = 8
_MAX_CONFLICTS = 3

_ACTION_TITLES = {
    "accept": "заявка принята",
    "decline": "отказ отправлен",
    "withdraw": "отказ от назначения отправлен",
    "visit-proposal": "предложение выезда отправлено",
    "repair-quote": "смета отправлена",
    "start-work": "начало работ отмечено",
    "complete": "завершение работ отправлено",
    "cancellation-response": "ответ на запрос отмены отправлен",
    "message": "сообщение заказчику отправлено",
}


def action_key(ref_key: str, data_version: str, planned: PlannedAction) -> str:
    expected = planned.body.get("expected_version")
    raw = f"{ref_key}|{data_version}|{planned.kind}|{expected}|{planned.fingerprint}"
    return f"onec-connector:{planned.kind}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


async def poll_once(state: AppState) -> int:
    """Один проход опроса. Возвращает число документов, у которых сменилась версия."""
    links = repo.list_active_links(state.conn)
    entity = state.profile.document.entity
    changed = 0
    size = max(1, state.settings.poll_batch_size)
    for start in range(0, len(links), size):
        batch = links[start : start + size]
        condition = " or ".join(f"Ref_Key eq {guid_literal(str(r['ref_key']))}" for r in batch)
        rows = await state.onec.query(entity, filter=condition, select=["Ref_Key", "DataVersion"])
        versions = {str(r["Ref_Key"]): str(r.get("DataVersion") or "") for r in rows}
        for link in batch:
            current = versions.get(str(link["ref_key"]))
            if current is None:
                logger.warning(
                    "документ %s заявки %s не найден в 1С", link["ref_key"], link["request_id"]
                )
                continue
            if current == (link["data_version"] or ""):
                continue
            changed += 1
            try:
                await evaluate(state, str(link["request_id"]))
            except (OneCUnreachableError, PlatformUnreachableError) as exc:
                logger.warning("опрос прерван: %s", exc)
                return changed
            except Exception:
                logger.exception("обработка документа %s не удалась", link["ref_key"])
    return changed


async def evaluate(state: AppState, request_id: str) -> list[str]:
    """Перечитать документ 1С заявки и выполнить положенные действия на платформе.
    Возвращает виды выполненных действий (для журнала и тестов)."""
    async with state.lock_for(request_id):
        return await evaluate_locked(state, request_id)


async def evaluate_locked(state: AppState, request_id: str) -> list[str]:
    link = repo.get_link(state.conn, request_id)
    if link is None or not link["active"]:
        return []
    entity = state.profile.document.entity
    ref_key = str(link["ref_key"])
    doc = await state.onec.get(entity, ref_key)
    if doc is None:
        logger.warning("документ %s удалён из 1С — заявка %s не отслеживается", ref_key, request_id)
        repo.deactivate_link(state.conn, request_id)
        return []
    try:
        view = await extract_view(state.directory, doc)
    except ProfileMismatchError as exc:
        logger.error("профиль не совпадает с базой 1С: %s", exc)
        await _report(state, ref_key, doc, [f"ошибка профиля: {exc}"])
        repo.set_link_data_version(state.conn, request_id, str(doc.get("DataVersion") or ""))
        return []

    card = repo.link_card(link)
    initial_version = card.get("version")
    done: list[str] = []
    notes: list[str] = []
    conflicts = 0

    def handled(kind: str, fp: str) -> bool:
        row = repo.find_action(state.conn, request_id=request_id, action=kind, fingerprint=fp)
        return row is not None and row["status"] in repo.FINAL_STATUSES

    content = content_fingerprint(view)
    fresh_topics: list[str] = []

    def changed_since(topic: str) -> bool:
        key = f"baseline:{request_id}:{topic}"
        stored = repo.get_setting(state.conn, key)
        if stored is None:
            repo.set_setting(state.conn, key, content)
            fresh_topics.append(topic)
            return False
        if stored == _CHANGED:
            return True
        if stored != content:
            repo.set_setting(state.conn, key, _CHANGED)
            return True
        return False

    for _ in range(_MAX_STEPS):
        planned = plan_actions(state.profile, view, card, handled, changed_since)
        if not planned:
            break
        step = planned[0]
        outcome, card = await _execute(state, request_id, ref_key, view.data_version, step, card)
        if outcome == "done":
            done.append(step.kind)
            notes.append(_ACTION_TITLES.get(step.kind, step.kind))
        elif outcome == "conflict":
            conflicts += 1
            if conflicts >= _MAX_CONFLICTS:
                notes.append("карточка на платформе меняется — повтор при следующем опросе")
                break
        elif outcome == "rejected":
            row = repo.find_action(
                state.conn, request_id=request_id, action=step.kind, fingerprint=step.fingerprint
            )
            detail = row["detail"] if row is not None else ""
            notes.append(f"платформа отклонила «{step.kind}»: {detail}")
        else:
            notes.append(f"«{step.kind}» не отправлено, повтор позже")
            break

    notes[:0] = [_waiting_hint(state, topic) for topic in fresh_topics]

    if card.get("version") != initial_version:
        doc = await documents.update_document(state, ref_key, card, with_messages=False) or doc
    if notes:
        doc = await _report(state, ref_key, doc, notes) or doc
    repo.set_link_data_version(state.conn, request_id, str(doc.get("DataVersion") or ""))
    return done


async def _execute(
    state: AppState,
    request_id: str,
    ref_key: str,
    data_version: str,
    planned: PlannedAction,
    card: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    existing = repo.find_action(
        state.conn, request_id=request_id, action=planned.kind, fingerprint=planned.fingerprint
    )
    if existing is not None and existing["status"] == "pending":
        row = existing
        body = dict(json.loads(existing["body_json"]))
    else:
        body = planned.body
        row = repo.create_action(
            state.conn,
            request_id=request_id,
            ref_key=ref_key,
            action=planned.kind,
            fingerprint=planned.fingerprint,
            data_version=data_version,
            idempotency_key=action_key(ref_key, data_version, planned),
            body=body,
        )
    try:
        result = await state.client.request_action(
            request_id, planned.path, body, idem_key=str(row["idempotency_key"])
        )
    except VersionConflictError as exc:
        repo.finish_action(state.conn, int(row["id"]), status="conflict", detail=str(exc))
        logger.info("409 VERSION_CONFLICT на %s заявки %s — перечитываю", planned.kind, request_id)
        return "conflict", await _refresh_card(state, request_id, card)
    except PlatformApiError as exc:
        if exc.status_code == 429 or exc.status_code >= 500:
            return _retry_later(state, row, str(exc)), card
        repo.finish_action(state.conn, int(row["id"]), status="rejected", detail=exc.message)
        logger.warning("платформа отклонила %s заявки %s: %s", planned.kind, request_id, exc)
        return "rejected", await _refresh_card(state, request_id, card)
    except PlatformUnreachableError as exc:
        return _retry_later(state, row, str(exc)), card

    repo.finish_action(state.conn, int(row["id"]), status="done")
    if planned.changes_version or not isinstance(result.get("version"), int):
        fallback = result if "status" in result else card
        return "done", await _refresh_card(state, request_id, fallback)
    return "done", card


_CHANGED = "changed"


def _waiting_hint(state: AppState, topic: str) -> str:
    """Подсказка пользователю 1С: чего ждёт событие платформы."""
    names: dict[str, str] = {}
    for name, stage in state.profile.state.stages.items():
        names.setdefault(stage, name)
    kind = topic.split(":", 1)[0]
    if kind == "cancellation":
        text = "заказчик просит отменить заявку"
        if "cancelled" in names:
            text += f": согласиться — состояние «{names['cancelled']}»"
        if "cancellation_declined" in names:
            text += f", оспорить — «{names['cancellation_declined']}» с причиной"
        return text
    if kind == "completion":
        return (
            "заказчик вернул заявку в работу: после доработки измените документ "
            "(итог работ или состояние) и отметьте выполнение снова"
        )
    return "предложение выезда отклонено или истекло: для повтора измените окно или сумму"


def _retry_later(state: AppState, row: Any, detail: str) -> str:
    attempts = int(row["attempts"]) + 1
    if attempts >= state.settings.action_max_attempts:
        repo.finish_action(state.conn, int(row["id"]), status="failed", detail=detail)
        return "rejected"
    state.conn.execute(
        "UPDATE outbound_actions SET attempts = ?, detail = ?, updated_at = ? WHERE id = ?",
        (attempts, detail[:2000], datetime.now(UTC).isoformat(), int(row["id"])),
    )
    state.conn.commit()
    return "later"


async def _refresh_card(state: AppState, request_id: str, card: dict[str, Any]) -> dict[str, Any]:
    try:
        fresh = await state.client.get_request(request_id)
    except (PlatformApiError, PlatformUnreachableError):
        return card
    if "status" in fresh:
        repo.update_link_card(state.conn, request_id, fresh)
        return fresh
    return card


async def _report(
    state: AppState, ref_key: str, doc: dict[str, Any], notes: list[str]
) -> dict[str, Any] | None:
    """Итог обмена — в реквизит документа, чтобы пользователь 1С видел результат."""
    target = state.profile.exchange_status
    if target is None:
        return None
    stamp = datetime.now(state.profile.zone()).strftime("%d.%m.%Y %H:%M")
    text = f"{stamp}: " + "; ".join(notes)
    try:
        body = await state.directory.build_patch(doc, {target: text[:1000]})
        if not body:
            return None
        return await state.onec.update(state.profile.document.entity, ref_key, body)
    except (OneCError, OneCUnreachableError, ProfileMismatchError) as exc:
        logger.warning("не удалось записать состояние обмена в 1С: %s", exc)
        return None
