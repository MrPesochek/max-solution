import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.adapters.http.ratelimit import ACCESS_REQUEST_LIMIT
from app.core import ids
from app.db import session as db_session
from app.db.models import AuditEntry, Notification
from tests.app_api.conftest import auth, idem
from tests.support import OTHER_INN, CustomerFixture, make_customer, org_id, session_token

pytestmark = pytest.mark.usefixtures("clean_db")


async def _employee_headers(key: str) -> tuple[dict[str, str], CustomerFixture]:
    customer = await make_customer(key)
    employee = customer.employee
    return auth(await session_token(employee), org_id(employee)), customer


async def _notifications() -> list[Notification]:
    async with db_session.transaction() as session:
        stmt = select(Notification).where(
            Notification.notification_type == "membership.access_requested"
        )
        return list((await session.execute(stmt)).scalars())


async def test_request_notifies_managers_and_hides_foreign_location(client: AsyncClient) -> None:
    headers, customer = await _employee_headers("acc-ok")
    foreign = await make_customer("acc-foreign", inn=OTHER_INN)
    own_location = ids.encode("location", customer.location_id)
    foreign_location = ids.encode("location", foreign.location_id)

    own = await client.post(
        "/memberships/me/access-requests",
        headers={**headers, **idem("acc-1")},
        json={"location_id": own_location, "note": "Нужна точка на Ленина"},
    )
    other = await client.post(
        "/memberships/me/access-requests",
        headers={**headers, **idem("acc-2")},
        json={"location_id": foreign_location},
    )
    missing = await client.post(
        "/memberships/me/access-requests",
        headers={**headers, **idem("acc-3")},
        json={"location_id": "loc_notarealid"},
    )
    assert own.status_code == other.status_code == missing.status_code == 202
    assert own.json() == other.json() == missing.json() == {"status": "sent"}

    rows = await _notifications()
    manager_user = customer.manager.user_id
    assert {r.recipient_user_id for r in rows} == {manager_user}
    locations = [r.payload["location_id"] for r in rows]
    assert locations == [own_location, None, None]

    async with db_session.transaction() as session:
        details = [
            row.details
            for row in (
                await session.execute(
                    select(AuditEntry).where(AuditEntry.action == "membership.access_request")
                )
            ).scalars()
        ]
    assert all("Ленина" not in str(d) for d in details)


async def test_request_rejects_request_id_and_is_rate_limited(client: AsyncClient) -> None:
    headers, _ = await _employee_headers("acc-lim")
    with_request = await client.post(
        "/memberships/me/access-requests",
        headers={**headers, **idem("acc-req")},
        json={"request_id": "req_x"},
    )
    assert with_request.status_code == 422
    for index in range(ACCESS_REQUEST_LIMIT):
        ok = await client.post(
            "/memberships/me/access-requests",
            headers={**headers, **idem(f"acc-l{index}")},
            json={},
        )
        assert ok.status_code == 202
    limited = await client.post(
        "/memberships/me/access-requests",
        headers={**headers, **idem("acc-over")},
        json={},
    )
    assert limited.status_code == 429
    assert (await client.post("/memberships/me/access-requests", json={})).status_code == 401
