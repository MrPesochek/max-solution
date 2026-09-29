from __future__ import annotations

from connector import repo


async def _assigned(harness, request_id: str = "req_1") -> None:
    harness.subscribe()
    harness.platform.add_request(request_id)
    response = await harness.deliver("request.assigned", request_id)
    assert response.status_code == 200


async def test_assigned_request_creates_work_order(harness) -> None:
    await _assigned(harness)

    link = repo.get_link(harness.state.conn, "req_1")
    assert link is not None
    doc = harness.doc("req_1")
    assert doc["Number"].startswith("ЗН00-")
    assert doc["Posted"] is False
    assert "Заявка платформы №101" in doc["Комментарий"]
    assert harness.prop("req_1", "Заявка платформы") == "№101 (req_1)"
    assert (
        harness.prop("req_1", "Неисправность") == "Не морозит холодильная витрина (код ошибки E1)"
    )
    assert harness.prop("req_1", "Статус на платформе") == "ожидает ответа сервиса"
    assert doc["Контрагент_Key"] != "00000000-0000-0000-0000-000000000000"
    assert harness.platform.external_references["req_1"].startswith(doc["Number"] + " от ")


async def test_unposted_change_is_ignored(harness) -> None:
    await _assigned(harness)
    harness.edit("req_1", state="Принят", post=False)

    await harness.poll()

    assert harness.platform.count("accept") == 0


async def test_accept_by_state_then_visit_proposal(harness) -> None:
    await _assigned(harness)
    version_before = harness.platform.requests["req_1"]["version"]

    harness.edit("req_1", state="Принят")
    assert await harness.poll() == 1

    card = harness.platform.requests["req_1"]
    assert card["status"] == "accepted"
    assert harness.platform.count("accept:applied") == 1
    assert harness.platform.idempotency_key_log[-1][0] == "accept"
    assert card["version"] > version_before
    assert "заявка принята" in (harness.prop("req_1", "Обмен с платформой") or "")

    await harness.deliver("request.assigned", "req_1")
    assert harness.prop("req_1", "Адрес объекта") == "Кафе на Ленина, ул. Ленина, 1"

    visit = harness.item_key("Выезд мастера (диагностика)")
    harness.edit(
        "req_1",
        Начало="2026-09-30T10:00:00",
        Окончание="2026-09-30T12:00:00",
        Работы=[{"Номенклатура_Key": visit, "Содержание": "", "Сумма": 1500}],
    )
    await harness.poll()

    proposals = harness.platform.requests["req_1"]["visit_proposals"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["visit_window_start"] == "2026-09-30T10:00:00+03:00"
    assert proposal["visit_window_end"] == "2026-09-30T12:00:00+03:00"
    assert proposal["price"]["amount_minor"] == 150000
    assert proposal["scope_description"] == "Выезд мастера (диагностика)"

    await harness.poll()
    harness.edit("req_1", Комментарий="внутренняя заметка")
    await harness.poll()
    assert harness.platform.count("visit_proposal:applied") == 1


async def test_full_cycle_estimate_start_complete(harness) -> None:
    await _assigned(harness)
    visit = harness.item_key("Выезд мастера (диагностика)")
    thermostat = harness.item_key("Замена термостата")
    harness.edit(
        "req_1",
        state="Принят",
        Начало="2026-09-30T10:00:00",
        Работы=[
            {"Номенклатура_Key": visit, "Сумма": 1500},
            {"Номенклатура_Key": thermostat, "Содержание": "Термостат ТАМ-145", "Сумма": 3200.5},
            {"Номенклатура_Key": harness.item_key("Заправка хладагентом"), "Сумма": 2500},
        ],
    )
    await harness.poll()

    card = harness.platform.requests["req_1"]
    assert card["status"] == "accepted"
    assert len(card["visit_proposals"]) == 1
    assert card["visit_proposals"][0]["visit_window_end"] == "2026-09-30T12:00:00+03:00"
    quote = card["repair_quotes"][0]
    assert quote["items"] == [
        {"title": "Термостат ТАМ-145", "amount_minor": 320050},
        {"title": "Заправка хладагентом", "amount_minor": 250000},
    ]
    assert quote["price"]["amount_minor"] == 570050

    harness.edit("req_1", state="В работе")
    await harness.poll()
    assert harness.platform.count("start_work") == 0

    harness.platform.approve_visit("req_1")
    await harness.deliver("visit_proposal.responded", "req_1")
    assert harness.platform.requests["req_1"]["status"] == "in_progress"

    harness.edit("req_1", state="Выполнен", props={"Итог работ": "Заменён термостат"})
    await harness.poll()
    card = harness.platform.requests["req_1"]
    assert card["status"] == "completion_reported"
    report = card["completion_report"]
    assert (report["outcome"], report["summary"]) == ("resolved", "Заменён термостат")


async def test_decline_by_state_with_reason(harness) -> None:
    await _assigned(harness)
    harness.edit("req_1", state="Отказ", props={"Причина отказа": "Нет запчастей"})

    await harness.poll()

    card = harness.platform.requests["req_1"]
    assert card["assignment"]["state"] == "declined"
    assert card["assignment"]["decline_reason"] == "Нет запчастей"


async def test_customer_comment_becomes_message_once(harness) -> None:
    await _assigned(harness)
    harness.edit("req_1", props={"Комментарий для заказчика": "Уточните код ошибки"})
    await harness.poll()
    harness.edit("req_1", Комментарий="ещё правка")
    await harness.poll()

    sent = [m["body"] for m in harness.platform.messages["req_1"]]
    assert sent == ["Уточните код ошибки"]


async def test_customer_messages_written_to_document(harness) -> None:
    await _assigned(harness)
    harness.platform.messages["req_1"].append(
        {
            "id": "msg_c1",
            "request_id": "req_1",
            "author_kind": "customer_member",
            "author_membership_id": "mem_1",
            "body": "Код ошибки E1, фото приложил",
            "created_at": "2026-09-19T10:05:00Z",
        }
    )
    harness.platform.bump("req_1")

    await harness.deliver("message.created", "req_1")

    assert harness.prop("req_1", "Сообщения заказчика") == (
        "2026-09-19 10:05: Код ошибки E1, фото приложил"
    )


async def test_cancelled_request_sets_state_and_stops_tracking(harness) -> None:
    await _assigned(harness)
    harness.platform.bump("req_1", status="cancelled")

    await harness.deliver("request.closed", "req_1")

    link = repo.get_link(harness.state.conn, "req_1")
    assert link is not None and link["active"] == 0
    states = await harness.state.directory.state_name(harness.doc("req_1"))
    assert states == "Отменен"


async def _accepted(harness, request_id: str = "req_1") -> None:
    await _assigned(harness, request_id)
    harness.edit(request_id, state="Принят")
    await harness.poll()
    assert harness.platform.requests[request_id]["status"] == "accepted"


async def _cancellation_requested(harness) -> None:
    harness.platform.request_cancellation("req_1")
    await harness.deliver("cancellation.requested", "req_1")


async def test_cancellation_accepted_by_state(harness) -> None:
    await _accepted(harness)
    await _cancellation_requested(harness)

    assert harness.prop("req_1", "Статус на платформе") == "заказчик просит отменить"
    assert "согласиться — состояние «Отменен»" in (
        harness.prop("req_1", "Обмен с платформой") or ""
    )
    assert harness.platform.count("cancellation_response") == 0

    harness.edit("req_1", state="Отменен")
    await harness.poll()

    card = harness.platform.requests["req_1"]
    assert harness.platform.count("cancellation_response:applied") == 1
    assert card["status"] == "cancelled"
    assert card["cancellation"]["status"] == "accepted"
    assert card["assignment"]["state"] == "revoked"
    assert harness.platform.idempotency_key_log[-1][0] == "cancellation_response"
    assert "ответ на запрос отмены отправлен" in (harness.prop("req_1", "Обмен с платформой") or "")

    await harness.deliver("assignment.revoked", "req_1", data={"request_id": "req_1"})
    link = repo.get_link(harness.state.conn, "req_1")
    assert link is not None and link["active"] == 0
    assert await harness.state.directory.state_name(harness.doc("req_1")) == "Отменен"
    await harness.poll()
    assert harness.platform.count("cancellation_response") == 1


async def test_cancellation_declined_with_reason(harness) -> None:
    await _accepted(harness)
    await _cancellation_requested(harness)

    harness.edit(
        "req_1",
        state="Отмена не согласована",
        props={"Причина несогласия с отменой": "Мастер уже выехал"},
    )
    await harness.poll()

    card = harness.platform.requests["req_1"]
    assert card["status"] == "accepted"
    assert card["cancellation"]["status"] == "disputed"
    assert card["cancellation"]["provider_response"] == "Мастер уже выехал"
    assert card["assignment"]["state"] == "accepted"

    harness.edit("req_1", Комментарий="заметка")
    await harness.poll()
    assert harness.platform.count("cancellation_response") == 1


async def test_cancellation_decline_without_reason_uses_default(harness) -> None:
    await _accepted(harness)
    await _cancellation_requested(harness)

    harness.edit("req_1", state="Отмена не согласована")
    await harness.poll()

    cancellation = harness.platform.requests["req_1"]["cancellation"]
    assert cancellation["status"] == "disputed"
    assert cancellation["provider_response"] == "Исполнитель не согласен с отменой"


async def test_state_set_before_cancellation_is_not_an_answer(harness) -> None:
    await _accepted(harness)
    harness.edit("req_1", state="Отменен")
    await harness.poll()
    await _cancellation_requested(harness)
    await harness.poll()
    harness.edit("req_1")
    await harness.poll()
    assert harness.platform.count("cancellation_response") == 0
    assert harness.platform.requests["req_1"]["status"] == "cancellation_pending"

    harness.edit(
        "req_1",
        state="Отмена не согласована",
        props={"Причина несогласия с отменой": "Работы уже идут"},
    )
    await harness.poll()
    assert harness.platform.requests["req_1"]["cancellation"]["status"] == "disputed"


async def test_cancelled_state_without_cancellation_request_sends_nothing(harness) -> None:
    await _accepted(harness)
    harness.edit("req_1", state="Отменен")
    await harness.poll()
    assert harness.platform.count("cancellation_response") == 0
    assert harness.platform.count("withdraw") == 0


async def _reported(harness) -> None:
    await _accepted(harness)
    visit = harness.item_key("Выезд мастера (диагностика)")
    harness.edit(
        "req_1", Начало="2026-09-30T10:00:00", Работы=[{"Номенклатура_Key": visit, "Сумма": 1500}]
    )
    await harness.poll()
    harness.platform.approve_visit("req_1")
    await harness.deliver("visit_proposal.responded", "req_1")
    harness.edit("req_1", state="В работе")
    await harness.poll()
    harness.edit("req_1", state="Выполнен", props={"Итог работ": "Заменён термостат"})
    await harness.poll()
    assert harness.platform.requests["req_1"]["status"] == "completion_reported"


async def test_completion_reported_again_after_customer_rejection(harness) -> None:
    await _reported(harness)

    harness.platform.reject_completion("req_1")
    await harness.deliver("request.changed", "req_1")
    assert harness.platform.count("complete:applied") == 1
    assert "вернул заявку в работу" in (harness.prop("req_1", "Обмен с платформой") or "")
    await harness.poll()
    assert harness.platform.count("complete:applied") == 1

    harness.edit("req_1", props={"Итог работ": "Заменён термостат, подтянуты клеммы"})
    await harness.poll()

    card = harness.platform.requests["req_1"]
    assert harness.platform.count("complete:applied") == 2
    assert card["status"] == "completion_reported"
    assert card["completion_report"]["summary"] == "Заменён термостат, подтянуты клеммы"


async def test_completion_after_rejection_via_state_round_trip(harness) -> None:
    await _reported(harness)
    harness.platform.reject_completion("req_1")
    await harness.deliver("request.changed", "req_1")

    harness.edit("req_1", state="В работе")
    await harness.poll()
    assert harness.platform.count("complete:applied") == 1
    harness.edit("req_1", state="Выполнен")
    await harness.poll()
    assert harness.platform.count("complete:applied") == 2
    assert harness.platform.requests["req_1"]["completion_report"]["outcome"] == "resolved"


async def test_same_visit_window_resent_after_rejection(harness) -> None:
    await _accepted(harness)
    visit = harness.item_key("Выезд мастера (диагностика)")
    works = [{"Номенклатура_Key": visit, "Сумма": 1500}]
    harness.edit("req_1", Начало="2026-09-30T10:00:00", Работы=works)
    await harness.poll()
    assert harness.platform.count("visit_proposal:applied") == 1

    harness.platform.reject_visit("req_1")
    await harness.deliver("visit_proposal.responded", "req_1")
    await harness.poll()
    assert harness.platform.count("visit_proposal:applied") == 1
    assert "предложение выезда отклонено" in (harness.prop("req_1", "Обмен с платформой") or "")

    harness.edit("req_1", Работы=[{"Номенклатура_Key": visit, "Сумма": 1200}])
    await harness.poll()
    harness.platform.reject_visit("req_1")
    await harness.deliver("visit_proposal.responded", "req_1")
    harness.edit("req_1", Работы=works)
    await harness.poll()

    proposals = harness.platform.requests["req_1"]["visit_proposals"]
    assert harness.platform.count("visit_proposal:applied") == 3
    assert [p["price"]["amount_minor"] for p in proposals] == [150000, 120000, 150000]
    assert proposals[-1]["status"] == "pending"
