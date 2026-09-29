from __future__ import annotations

from connector import repo
from connector.services import outbound


async def _accepted_in_onec(harness, request_id: str = "req_1") -> None:
    harness.subscribe()
    harness.platform.add_request(request_id)
    await harness.deliver("request.assigned", request_id)
    harness.edit(request_id, state="Принят")


async def test_lost_response_is_replayed_with_same_key(harness) -> None:
    await _accepted_in_onec(harness)
    harness.platform.lose_response_once.add("accept")

    await harness.poll()

    keys = harness.platform.keys_for("accept")
    assert len(keys) == 2 and keys[0] == keys[1]
    assert harness.platform.count("accept:applied") == 1
    assert harness.platform.count("accept:replay") == 1
    assert harness.platform.requests["req_1"]["status"] == "accepted"


async def test_platform_down_keeps_action_pending_and_reuses_key(harness) -> None:
    await _accepted_in_onec(harness)
    harness.platform.fail_times["accept"] = 100

    await harness.poll()
    actions = repo.list_actions(harness.state.conn, "req_1")
    assert [a["status"] for a in actions] == ["pending"]
    first_key = actions[0]["idempotency_key"]

    harness.edit("req_1", Комментарий="перезаписан")
    harness.platform.fail_times["accept"] = 0
    await harness.poll()

    actions = repo.list_actions(harness.state.conn, "req_1")
    assert [a["status"] for a in actions if a["action"] == "accept"] == ["done"]
    assert set(harness.platform.keys_for("accept")) == {first_key}
    assert harness.platform.count("accept:applied") == 1


async def test_version_conflict_rereads_card_and_retries(harness) -> None:
    await _accepted_in_onec(harness)
    harness.platform.conflict_once.add("accept")

    await harness.poll()

    actions = [a for a in repo.list_actions(harness.state.conn, "req_1") if a["action"] == "accept"]
    assert [a["status"] for a in actions] == ["conflict", "done"]
    assert actions[0]["idempotency_key"] != actions[1]["idempotency_key"]
    assert harness.platform.requests["req_1"]["status"] == "accepted"


async def test_rejected_action_is_logged_and_not_repeated(harness) -> None:
    await _accepted_in_onec(harness)
    await harness.poll()
    harness.platform.bump("req_1", status="scheduled")
    await harness.deliver("request.changed", "req_1")
    harness.platform.requests["req_1"]["status"] = "cancellation_pending"
    harness.edit("req_1", state="В работе")

    await harness.poll()
    harness.edit("req_1", Комментарий="ещё раз записали")
    await harness.poll()

    started = [
        a for a in repo.list_actions(harness.state.conn, "req_1") if a["action"] == "start-work"
    ]
    assert [a["status"] for a in started] == ["rejected"]
    assert "INVALID_TRANSITION" not in started[0]["detail"]
    assert harness.platform.count("start_work") == 1
    assert "отклонила «start-work»" in (harness.prop("req_1", "Обмен с платформой") or "")


async def test_action_key_depends_on_data_version(harness) -> None:
    from connector.actions import PlannedAction

    planned = PlannedAction(
        kind="accept", path="accept", fingerprint="fp", body={"expected_version": 3}
    )
    a = outbound.action_key("ref", "AAAAAQ==", planned)
    b = outbound.action_key("ref", "AAAAAg==", planned)
    assert a != b
    assert a == outbound.action_key("ref", "AAAAAQ==", planned)
    assert a.startswith("onec-connector:accept:")
