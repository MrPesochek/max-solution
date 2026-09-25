from __future__ import annotations

import base64
import logging
from typing import Any

from connector import repo
from connector.onec_client import guid_literal, string_literal
from connector.state import AppState

logger = logging.getLogger("onec_connector.attachments")

SLOT_LABELS = {
    "overview": "общий вид",
    "nameplate": "шильдик",
    "display_error": "экран / код ошибки",
}
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def file_description(item: dict[str, Any]) -> str:
    slot = item.get("slot")
    label = SLOT_LABELS.get(str(slot), str(slot)) if slot else "фото"
    return f"Платформа: {label} ({item['id']})"


async def sync_to_onec(state: AppState, request_id: str, ref_key: str, card: dict[str, Any]) -> int:
    """Выгрузить в 1С готовые вложения, которых там ещё нет. Возвращает число выгруженных."""
    spec = state.profile.attachments
    ready = [
        item
        for item in card.get("attachments") or []
        if item.get("id") and item.get("processing_state") == "ready"
    ]
    uploaded = 0
    if spec.mode == "attached_files":
        for item in ready:
            if repo.attachment_uploaded(state.conn, str(item["id"])):
                continue
            if await _upload(state, request_id, ref_key, item):
                uploaded += 1
    if spec.list_field is not None and ready:
        await _write_list(state, ref_key, ready)
    return uploaded


async def _upload(state: AppState, request_id: str, ref_key: str, item: dict[str, Any]) -> bool:
    spec = state.profile.attachments
    assert spec.catalog is not None and spec.binary_register is not None
    attachment_id = str(item["id"])
    declared = int(item.get("byte_size") or 0)
    if declared > state.settings.attachment_max_bytes:
        logger.warning("вложение %s больше лимита (%s байт) — пропущено", attachment_id, declared)
        return False
    content, content_type = await state.client.download_attachment(attachment_id)
    if len(content) > state.settings.attachment_max_bytes:
        logger.warning("вложение %s больше лимита — пропущено", attachment_id)
        return False

    description = file_description(item)
    existing = await state.onec.query(
        spec.catalog,
        filter=(
            f"{spec.owner_field} eq {guid_literal(ref_key)} "
            f"and Description eq {string_literal(description)}"
        ),
        select=["Ref_Key"],
        top=1,
    )
    if existing:
        file_key = str(existing[0]["Ref_Key"])
    else:
        mime = content_type.split(";")[0].strip() or str(item.get("mime_type") or "")
        created = await state.onec.create(
            spec.catalog,
            {
                "Description": description,
                spec.owner_field: ref_key,
                "Расширение": _EXTENSIONS.get(mime, "bin"),
                "Размер": len(content),
                "ТипХраненияФайла": "ВИнформационнойБазе",
                "Описание": f"Заявка платформы {request_id}",
            },
        )
        file_key = str(created["Ref_Key"])

    binary = await state.onec.query(
        spec.binary_register,
        filter=f"{spec.binary_file_field} eq {guid_literal(file_key)}",
        top=1,
    )
    if not binary:
        await state.onec.create(
            spec.binary_register,
            {
                spec.binary_file_field: file_key,
                f"{spec.binary_file_field}_Type": f"StandardODATA.{spec.catalog}",
                spec.binary_data_field: base64.b64encode(content).decode(),
            },
        )
    repo.save_uploaded_attachment(
        state.conn,
        attachment_id=attachment_id,
        request_id=request_id,
        file_ref_key=file_key,
        size_bytes=len(content),
        content_type=content_type,
    )
    logger.info("фото %s выгружено в 1С (%s)", attachment_id, file_key)
    return True


async def _write_list(state: AppState, ref_key: str, ready: list[dict[str, Any]]) -> None:
    spec = state.profile.attachments
    assert spec.list_field is not None
    uploaded = {
        str(r["attachment_id"])
        for r in state.conn.execute("SELECT attachment_id FROM uploaded_attachments").fetchall()
    }
    lines = []
    for item in ready:
        mark = "в присоединённых файлах" if str(item["id"]) in uploaded else "на платформе"
        sensitive = (
            ", конфиденциально" if item.get("visibility_class") == "request_sensitive" else ""
        )
        lines.append(f"{file_description(item)} — {mark}{sensitive}")
    entity = state.profile.document.entity
    doc = await state.onec.get(entity, ref_key)
    if doc is None:
        return
    body = await state.directory.build_patch(doc, {spec.list_field: "\n".join(lines)})
    if body:
        await state.onec.update(entity, ref_key, body)
