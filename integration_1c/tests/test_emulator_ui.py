from __future__ import annotations

from connector import repo


async def test_login_requires_csrf(harness) -> None:
    response = await harness.emulator_client.post("/login", data={"password": "user-pass"})
    assert response.status_code == 403


async def test_wrong_password(harness) -> None:
    page = await harness.emulator_client.get("/login")
    import re

    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = await harness.emulator_client.post(
        "/login", data={"password": "nope", "csrf_token": token}
    )
    assert response.status_code == 401


async def test_orders_require_login(harness) -> None:
    response = await harness.emulator_client.get("/ui/orders")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


async def test_form_state_change_accepts_request(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_ui")
    harness.platform.add_attachment("att_ui", "req_ui")
    await harness.deliver("request.assigned", "req_ui")
    ref_key = str(repo.get_link(harness.state.conn, "req_ui")["ref_key"])
    await harness.ui_login()

    listing = await harness.emulator_client.get("/ui/orders")
    assert "№101 (req_ui)" in listing.text
    token = await harness.ui_form_token(ref_key)
    form = await harness.emulator_client.get(f"/ui/orders/{ref_key}")
    assert "Платформа: общий вид (att_ui)" in form.text

    rejected = await harness.emulator_client.post(
        f"/ui/orders/{ref_key}", data={"state": "Принят", "action": "post"}
    )
    assert rejected.status_code == 403

    response = await harness.emulator_client.post(
        f"/ui/orders/{ref_key}",
        data={"state": "Принят", "action": "post", "csrf_token": token},
    )
    assert response.status_code == 303
    assert harness.doc("req_ui")["Posted"] is True

    await harness.poll()
    assert harness.platform.requests["req_ui"]["status"] == "accepted"

    visit = harness.item_key("Выезд мастера (диагностика)")
    token = await harness.ui_form_token(ref_key)
    await harness.emulator_client.post(
        f"/ui/orders/{ref_key}",
        data={
            "start": "2026-10-01T09:00",
            "end": "2026-10-01T11:00",
            "row-0-item": visit,
            "row-0-content": "",
            "row-0-amount": "1500,00",
            "action": "post",
            "csrf_token": token,
        },
    )
    await harness.poll()
    proposal = harness.platform.requests["req_ui"]["visit_proposals"][-1]
    assert proposal["price"]["amount_minor"] == 150000
    assert proposal["visit_window_start"] == "2026-10-01T09:00:00+03:00"


async def test_attached_file_download(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_file")
    harness.platform.add_attachment("att_f", "req_file", content=b"\xff\xd8photo")
    await harness.deliver("request.assigned", "req_file")
    await harness.ui_login()
    from emulator import store
    from emulator.metadata import FILES

    file_key = store.list_all(harness.emulator.conn, FILES)[0]["Ref_Key"]
    response = await harness.emulator_client.get(f"/ui/files/{file_key}")

    assert response.status_code == 200
    assert response.content == b"\xff\xd8photo"
    assert response.headers["content-type"] == "image/jpeg"


async def test_form_shows_cancellation_request_and_answer(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_cancel")
    await harness.deliver("request.assigned", "req_cancel")
    harness.edit("req_cancel", state="Принят")
    await harness.poll()
    ref_key = str(repo.get_link(harness.state.conn, "req_cancel")["ref_key"])
    await harness.ui_login()

    form = await harness.emulator_client.get(f"/ui/orders/{ref_key}")
    assert "Заказчик просит отменить заявку" not in form.text

    harness.platform.request_cancellation("req_cancel")
    await harness.deliver("cancellation.requested", "req_cancel")
    form = await harness.emulator_client.get(f"/ui/orders/{ref_key}")
    assert "Заказчик просит отменить заявку" in form.text
    assert "Отмена не согласована" in form.text
    assert "Причина несогласия с отменой" in form.text

    token = await harness.ui_form_token(ref_key)
    await harness.emulator_client.post(
        f"/ui/orders/{ref_key}",
        data={
            "state": "Отмена не согласована",
            "prop:Причина несогласия с отменой": "Запчасти уже заказаны",
            "action": "post",
            "csrf_token": token,
        },
    )
    await harness.poll()
    cancellation = harness.platform.requests["req_cancel"]["cancellation"]
    assert cancellation["status"] == "disputed"
    assert cancellation["provider_response"] == "Запчасти уже заказаны"
