import pytest
from httpx import ASGITransport, AsyncClient

from app.core import ids
from app.db import session as db_session
from app.db.models import Organization
from app.main import create_app
from tests import factories
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import org_id, session_token

pytestmark = pytest.mark.usefixtures("clean_db", "settings")


def _auth(token: str, organization_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization_id:
        headers["X-Organization-Id"] = organization_id
    return headers


def _idem(key: str) -> dict[str, str]:
    return {"Idempotency-Key": f"test-key-{key}"}


async def test_review_submitted_via_app_api_then_moderated_via_operator_api(world: World) -> None:
    completed = await h.make_completion_reported(world)
    app = create_app()
    manager_token = await session_token(world.manager)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver/app-api/v1"
    ) as client:
        put = await client.put(
            f"/requests/{ids.encode('request', h.rid(completed))}/review",
            headers={**_auth(manager_token, org_id(world.manager)), **_idem("review-http")},
            json={"rating": 5, "text": "Отлично", "show_customer_name": True},
        )
        assert put.status_code == 200, put.text
        review_id = put.json()["id"]

        state = await client.get(
            f"/requests/{ids.encode('request', h.rid(completed))}/review",
            headers=_auth(manager_token, org_id(world.manager)),
        )
        assert state.status_code == 200
        assert state.json()["review"]["id"] == review_id

    async with db_session.transaction() as session:
        operator_user = await factories.create_user(session, max_user_id="op-http-review")
        await factories.create_platform_role(session, operator_user)
        operator_token = await factories.create_session_token(session, operator_user)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver/operator-api/v1"
    ) as client:
        decide = await client.post(
            f"/reviews/{review_id}/decision",
            headers={**_auth(operator_token), **_idem("decide-http")},
            json={"decision": "published", "reason": "содержание уместно"},
        )
        assert decide.status_code == 200, decide.text
        assert decide.json()["moderation_status"] == "published"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver/app-api/v1"
    ) as client:
        listing = await client.get(
            f"/providers/{org_id(world.provider_admin)}/reviews", headers=_auth(manager_token)
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [review_id]


async def test_integration_reviews_require_scope(world: World) -> None:
    completed = await h.make_completion_reported(world)
    app = create_app()
    manager_token = await session_token(world.manager)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver/app-api/v1"
    ) as client:
        put = await client.put(
            f"/requests/{ids.encode('request', h.rid(completed))}/review",
            headers={**_auth(manager_token, org_id(world.manager)), **_idem("review-scope")},
            json={"rating": 4},
        )
        review = put.json()

    async with db_session.transaction() as session:
        provider_org = await session.get(Organization, world.provider_org_id)
        assert provider_org is not None
        _, no_scope_key = await factories.create_integration_client(
            session, provider_org, scopes=("requests:read",)
        )
        _, read_scope_key = await factories.create_integration_client(
            session, provider_org, scopes=("reviews:read",)
        )
        _, write_scope_key = await factories.create_integration_client(
            session, provider_org, scopes=("reviews:write",)
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver/api/v1"
    ) as client:
        forbidden = await client.get("/reviews", headers=_auth(no_scope_key))
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "INSUFFICIENT_SCOPE"

        allowed = await client.get("/reviews", headers=_auth(read_scope_key))
        assert allowed.status_code == 200

        reply_denied = await client.post(
            f"/reviews/{review['id']}/reply",
            headers={**_auth(no_scope_key), **_idem("reply-scope-1")},
            json={"body": "Спасибо"},
        )
        assert reply_denied.status_code == 403

        reply_ok = await client.post(
            f"/reviews/{review['id']}/reply",
            headers={**_auth(write_scope_key), **_idem("reply-scope-2")},
            json={"body": "Спасибо за отзыв"},
        )
        assert reply_ok.status_code == 201, reply_ok.text
