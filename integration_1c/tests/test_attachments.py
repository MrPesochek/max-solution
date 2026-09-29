from __future__ import annotations

import base64

from connector import repo
from emulator import store
from emulator.metadata import BINARY, FILES

PHOTO = b"\xff\xd8\xff\xe0real-jpeg-bytes"


async def test_ready_photo_attached_to_document(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_ph")
    harness.platform.add_attachment("att_1", "req_ph", content=PHOTO, slot="nameplate")

    await harness.deliver("request.assigned", "req_ph")

    doc = harness.doc("req_ph")
    files = store.list_all(harness.emulator.conn, FILES)
    assert len(files) == 1
    assert files[0]["ВладелецФайла_Key"] == doc["Ref_Key"]
    assert files[0]["Расширение"] == "jpg"
    assert files[0]["Размер"] == len(PHOTO)
    assert files[0]["Description"] == "Платформа: шильдик (att_1)"
    binary = store.list_all(harness.emulator.conn, BINARY)
    assert base64.b64decode(binary[0]["ДвоичныеДанныеФайла_Base64Data"]) == PHOTO
    assert store.file_content(harness.emulator.conn, files[0]["Ref_Key"]) == PHOTO
    assert "в присоединённых файлах" in (harness.prop("req_ph", "Фото с платформы") or "")


async def test_quarantined_photo_waits_for_ready(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_q")
    meta = harness.platform.add_attachment("att_q", "req_q", processing_state="quarantined")

    await harness.deliver("request.assigned", "req_q")
    assert store.list_all(harness.emulator.conn, FILES) == []
    assert harness.platform.count("download_attachment") == 0

    meta["processing_state"] = "ready"
    harness.platform.bump("req_q")
    await harness.deliver("request.changed", "req_q")

    assert len(store.list_all(harness.emulator.conn, FILES)) == 1


async def test_repeated_events_do_not_duplicate_files(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_rep")
    harness.platform.add_attachment("att_r", "req_rep")
    await harness.deliver("request.assigned", "req_rep")
    for _ in range(2):
        harness.platform.bump("req_rep")
        await harness.deliver("request.changed", "req_rep")

    assert len(store.list_all(harness.emulator.conn, FILES)) == 1
    assert harness.platform.count("download_attachment") == 1


async def test_file_created_before_crash_is_reused(harness) -> None:
    """Элемент справочника создан, а запись о выгрузке не сохранилась (падение) —
    повтор находит элемент по наименованию и дописывает только двоичные данные."""
    harness.subscribe()
    harness.platform.add_request("req_cr")
    harness.platform.add_attachment("att_c", "req_cr")
    await harness.deliver("request.assigned", "req_cr")
    harness.state.conn.execute("DELETE FROM uploaded_attachments")
    harness.emulator.conn.execute("DELETE FROM objects WHERE entity = ?", (BINARY,))
    harness.emulator.conn.commit()

    harness.platform.bump("req_cr")
    await harness.deliver("request.changed", "req_cr")

    assert len(store.list_all(harness.emulator.conn, FILES)) == 1
    assert len(store.list_all(harness.emulator.conn, BINARY)) == 1


async def test_oversized_photo_is_skipped(harness) -> None:
    harness.subscribe()
    harness.state.settings.attachment_max_bytes = 10
    harness.platform.add_request("req_big")
    harness.platform.add_attachment("att_big", "req_big", content=b"x" * 11)
    harness.platform.add_attachment("att_small", "req_big", content=b"y" * 5)

    await harness.deliver("request.assigned", "req_big")

    files = store.list_all(harness.emulator.conn, FILES)
    assert [f["Description"] for f in files] == ["Платформа: общий вид (att_small)"]
    assert repo.attachment_uploaded(harness.state.conn, "att_big") is False
