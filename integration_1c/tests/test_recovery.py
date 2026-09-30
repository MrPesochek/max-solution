from __future__ import annotations

from connector import repo
from connector.services import recovery, sync
from emulator import store
from emulator.metadata import ORDER
from tests.fake_platform import make_envelope


async def test_missed_webhooks_recovered_from_events(harness) -> None:
    for request_id in ("req_e1", "req_e2"):
        harness.platform.add_request(request_id)
        harness.platform.events.append(
            make_envelope(
                event_id=f"evt_{request_id}",
                event_type="request.assigned",
                resource_id=request_id,
                resource_version=1,
            )
        )

    result = await sync.reconcile(harness.state)

    assert result.mode == "events"
    assert result.applied == 2
    assert len(store.list_all(harness.emulator.conn, ORDER)) == 2
    assert repo.get_cursor(harness.state.conn) == "2"

    again = await sync.reconcile(harness.state)
    assert again.applied == 0
    assert len(store.list_all(harness.emulator.conn, ORDER)) == 2


async def test_event_seen_by_webhook_is_skipped_in_events(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_w")
    await harness.deliver("request.assigned", "req_w", event_id="evt_same")
    harness.platform.events.append(
        make_envelope(
            event_id="evt_same",
            event_type="request.assigned",
            resource_id="req_w",
            resource_version=1,
        )
    )

    result = await sync.reconcile(harness.state)

    assert result.skipped_duplicates == 1
    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1


async def test_expired_cursor_falls_back_to_full_sync(harness) -> None:
    repo.set_cursor(harness.state.conn, "999")
    harness.platform.cursor_expired = True
    harness.platform.add_request("req_f1")
    harness.platform.add_request("req_f2")

    result = await sync.reconcile(harness.state)

    assert result.mode == "full"
    assert result.applied == 2
    assert repo.get_link(harness.state.conn, "req_f1") is not None
    assert repo.get_cursor(harness.state.conn) != "999"


async def test_received_but_unprocessed_event_is_resumed(harness) -> None:
    harness.platform.add_request("req_crash")
    envelope = make_envelope(
        event_id="evt_crash",
        event_type="request.assigned",
        resource_id="req_crash",
        resource_version=1,
    )
    repo.reserve_event(
        harness.state.conn,
        event_id="evt_crash",
        delivery_id="d1",
        event_type="request.assigned",
        resource_id="req_crash",
        resource_version=1,
        payload=envelope,
    )

    assert recovery.resume_unprocessed(harness.state) == 1
    await harness.drain()

    assert repo.get_link(harness.state.conn, "req_crash") is not None
    assert repo.list_unprocessed_events(harness.state.conn) == []


async def test_onec_down_during_event_is_retried(harness, monkeypatch) -> None:
    harness.subscribe()
    harness.platform.add_request("req_down")
    original = harness.state.onec.create
    calls = {"n": 0}

    async def flaky(entity, body):
        calls["n"] += 1
        if calls["n"] == 1:
            from connector.onec_client import OneCUnreachableError

            raise OneCUnreachableError("сервер 1С недоступен")
        return await original(entity, body)

    monkeypatch.setattr(harness.state.onec, "create", flaky)
    await harness.deliver("request.assigned", "req_down")

    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1
    assert repo.get_link(harness.state.conn, "req_down") is not None


async def test_external_reference_retried_after_failure(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_ext")
    harness.platform.fail_times["external_reference"] = 10
    await harness.deliver("request.assigned", "req_ext")
    assert "req_ext" not in harness.platform.external_references

    harness.platform.fail_times["external_reference"] = 0
    harness.platform.bump("req_ext")
    await harness.deliver("request.changed", "req_ext")

    assert harness.platform.external_references["req_ext"].startswith("ЗН00-000001 от ")
    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1
