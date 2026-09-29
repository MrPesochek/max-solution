from __future__ import annotations

from connector import repo
from connector.services.bootstrap import ensure_subscription


async def test_subscription_created_once(harness) -> None:
    assert await ensure_subscription(harness.state) is True
    assert await ensure_subscription(harness.state) is True

    assert harness.platform.count("create_subscription") == 1
    assert harness.platform.subscription["url"] == "http://connector.test/webhooks/platform"
    assert "request.assigned" in harness.platform.subscription["events"]
    saved = repo.get_subscription(harness.state.conn)
    assert saved is not None and saved["secret"] == "test-secret-value"


async def test_status_endpoint_has_no_request_data(harness) -> None:
    harness.subscribe()
    harness.platform.add_request("req_s")
    await harness.deliver("request.assigned", "req_s")

    response = await harness.client.get("/status")

    assert response.json() == {
        "profile": "unf",
        "subscription": True,
        "active_links": 1,
        "events_cursor": None,
        "failed_events": 0,
        "dead_events": 0,
    }
