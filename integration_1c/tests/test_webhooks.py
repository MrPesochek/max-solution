from __future__ import annotations

import json
import time

from connector import repo
from emulator import store
from emulator.metadata import ORDER
from tests.conftest import SECRET
from tests.fake_platform import make_envelope, signed_headers


def _body(request_id: str, event_id: str) -> bytes:
    envelope = make_envelope(
        event_id=event_id, event_type="request.assigned", resource_id=request_id, resource_version=1
    )
    return json.dumps(envelope).encode()


async def test_valid_signature_creates_document(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_ok")
    body = _body("req_ok", "evt_ok")

    response = await harness.client.post(
        "/webhooks/platform",
        content=body,
        headers=signed_headers(SECRET, body, event_id="evt_ok", delivery_id="d1"),
    )
    await harness.drain()

    assert response.status_code == 200
    assert repo.get_link(harness.state.conn, "req_ok") is not None


async def test_wrong_secret_is_rejected(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_bad")
    body = _body("req_bad", "evt_bad")

    response = await harness.client.post(
        "/webhooks/platform",
        content=body,
        headers=signed_headers("wrong", body, event_id="evt_bad", delivery_id="d1"),
    )
    await harness.drain()

    assert response.status_code == 401
    assert repo.get_link(harness.state.conn, "req_bad") is None
    assert store.list_all(harness.emulator.conn, ORDER) == []


async def test_tampered_body_is_rejected(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_t")
    body = _body("req_t", "evt_t")
    headers = signed_headers(SECRET, body, event_id="evt_t", delivery_id="d1")

    response = await harness.client.post(
        "/webhooks/platform", content=body.replace(b"req_t", b"req_x"), headers=headers
    )

    assert response.status_code == 401


async def test_timestamp_outside_window_is_rejected(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_old")
    body = _body("req_old", "evt_old")
    for shift in (-301, 301):
        headers = signed_headers(
            SECRET, body, event_id="evt_old", delivery_id="d1", timestamp=int(time.time()) + shift
        )
        response = await harness.client.post("/webhooks/platform", content=body, headers=headers)
        assert response.status_code == 401
    headers = signed_headers(
        SECRET, body, event_id="evt_old", delivery_id="d2", timestamp=int(time.time()) - 290
    )
    response = await harness.client.post("/webhooks/platform", content=body, headers=headers)
    assert response.status_code == 200


async def test_no_subscription_rejects(harness) -> None:
    harness.platform.add_request("req_ns")
    body = _body("req_ns", "evt_ns")

    response = await harness.client.post(
        "/webhooks/platform",
        content=body,
        headers=signed_headers(SECRET, body, event_id="evt_ns", delivery_id="d1"),
    )

    assert response.status_code == 401


async def test_duplicate_event_creates_one_document(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_dup")
    body = _body("req_dup", "evt_dup")

    for delivery in ("d1", "d2", "d3"):
        response = await harness.client.post(
            "/webhooks/platform",
            content=body,
            headers=signed_headers(SECRET, body, event_id="evt_dup", delivery_id=delivery),
        )
        assert response.status_code == 200
        await harness.drain()

    assert len(store.list_all(harness.emulator.conn, ORDER)) == 1
    assert harness.platform.count("external_reference:applied") == 1
    outcomes = [r["outcome"] for r in repo.recent_deliveries(harness.state.conn)]
    assert outcomes.count("duplicate") == 2


async def test_older_event_does_not_overwrite(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_ord")
    await harness.deliver("request.assigned", "req_ord", event_id="evt_new")
    stored = repo.get_link(harness.state.conn, "req_ord")
    assert stored is not None
    calls = harness.platform.count("get_request")

    await harness.deliver("request.changed", "req_ord", version=1, event_id="evt_stale")

    assert harness.platform.count("get_request") == calls


async def test_ping_is_acknowledged_without_document(harness) -> None:
    harness.subscribe()
    envelope = make_envelope(
        event_id="evt_ping", event_type="ping", resource_id="whs_1", resource_version=None
    )
    body = json.dumps(envelope).encode()

    response = await harness.client.post(
        "/webhooks/platform",
        content=body,
        headers=signed_headers(SECRET, body, event_id="evt_ping", delivery_id="d1"),
    )
    await harness.drain()

    assert response.status_code == 200
    assert store.list_all(harness.emulator.conn, ORDER) == []
