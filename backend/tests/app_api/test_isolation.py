from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core import ids
from app.db import session as db_session
from tests import factories
from tests.app_api.conftest import auth, idem

pytestmark = pytest.mark.usefixtures("clean_db")


@dataclass(slots=True)
class Org:
    token: str
    organization_id: str
    membership_id: str
    location_id: str
    equipment_id: str
    invitation_id: str


async def _org(name: str, key: str, *, inn: str | None = None) -> Org:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name=name, inn=inn)
        location = await factories.create_location(s, org)
        equipment = await factories.create_equipment(s, org, location)
        user = await factories.create_user(s, max_user_id=key)
        membership = await factories.create_membership(s, user, org)
        invitation, _token = await factories.create_invitation(s, org)
        token = await factories.create_session_token(s, user)
        return Org(
            token=token,
            organization_id=ids.encode("organization", org.id),
            membership_id=ids.encode("membership", membership.id),
            location_id=ids.encode("location", location.id),
            equipment_id=ids.encode("equipment", equipment.id),
            invitation_id=ids.encode("invitation", invitation.id),
        )


async def test_foreign_objects_are_not_found(client: AsyncClient) -> None:
    mine = await _org("Моя", "iso-mine")
    other = await _org("Чужая", "iso-other")
    headers = auth(mine.token, mine.organization_id)

    assert (await client.get(f"/locations/{other.location_id}", headers=headers)).status_code == 404
    assert (
        await client.get(f"/equipment/{other.equipment_id}", headers=headers)
    ).status_code == 404
    assert (
        await client.get("/equipment", params={"location_id": other.location_id}, headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/memberships/{other.membership_id}/revoke",
            headers={**headers, **idem("iso-rev-1")},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/invitations/{other.invitation_id}/revoke",
            headers={**headers, **idem("iso-rev-2")},
        )
    ).status_code == 404

    members = (await client.get("/memberships", headers=headers)).json()["items"]
    assert [m["id"] for m in members] == [mine.membership_id]
    invitations = (await client.get("/invitations", headers=headers)).json()["items"]
    assert [i["id"] for i in invitations] == [mine.invitation_id]


async def test_foreign_organization_header_is_not_found(client: AsyncClient) -> None:
    """A27/A30: знание идентификатора организации не даёт контекста в ней."""
    mine = await _org("Моя", "iso-hdr-mine", inn="7707083893")
    other = await _org("Чужая", "iso-hdr-other", inn="7707083893")

    response = await client.get(
        "/organizations/current", headers=auth(mine.token, other.organization_id)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_malformed_public_id_behaves_as_missing(client: AsyncClient) -> None:
    mine = await _org("Моя", "iso-bad-id")
    headers = auth(mine.token, mine.organization_id)

    assert (await client.get("/locations/loc_не-такой", headers=headers)).status_code == 404
    assert (await client.get(f"/locations/{mine.equipment_id}", headers=headers)).status_code == 404
    assert (
        await client.get("/organizations/current", headers=auth(mine.token, "org_123"))
    ).status_code == 404


async def test_organization_context_is_required_for_org_data(client: AsyncClient) -> None:
    mine = await _org("Моя", "iso-no-org")
    assert (await client.get("/locations", headers=auth(mine.token))).status_code == 403
    assert (await client.get("/me", headers=auth(mine.token))).status_code == 200


async def test_preview_token_never_reaches_logs(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """ТЗ 6.7: единственный токен в URL не попадает ни в журнал запросов, ни в ответ об ошибке."""
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name="Журнал")
        user = await factories.create_user(s, max_user_id="log-preview")
        await factories.create_membership(s, user, org)
        _invitation, invite_token = await factories.create_invitation(s, org)
        session_token = await factories.create_session_token(s, user)

    capsys.readouterr()
    response = await client.get(
        "/invitations/preview",
        params={"token": invite_token},
        headers=auth(session_token),
    )
    assert response.status_code == 200

    captured = capsys.readouterr().out
    assert "/app-api/v1/invitations/preview" in captured
    assert invite_token not in captured
    assert "token" not in captured


async def test_preview_accepts_token_in_body(client: AsyncClient, app: FastAPI) -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name="Тело")
        user = await factories.create_user(s, max_user_id="body-preview")
        await factories.create_membership(s, user, org)
        _invitation, invite_token = await factories.create_invitation(s, org)
        session_token = await factories.create_session_token(s, user)

    response = await client.post(
        "/invitations/preview", json={"token": invite_token}, headers=auth(session_token)
    )
    assert response.status_code == 200
    assert response.json()["organization_name"] == "Тело"

    paths = app.openapi()["paths"]
    assert paths["/app-api/v1/invitations/preview"]["get"]["deprecated"] is True
    assert "post" in paths["/app-api/v1/service-binding-invitations/preview"]


async def test_dual_organization_context_is_chosen_by_membership(client: AsyncClient) -> None:
    """ТЗ 3: две роли в одной организации — контекст задаёт X-Membership-Id."""
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name="Двойная")
        user = await factories.create_user(s, max_user_id="iso-dual")
        await factories.create_membership(s, user, org)
        token = await factories.create_session_token(s, user)
    org_id = ids.encode("organization", org.id)

    added = await client.post(
        f"/organizations/{org_id}/participation",
        json={"kind": "provider"},
        headers={**auth(token, org_id), **idem("iso-dual-add")},
    )
    assert added.status_code == 201
    provider_membership = added.json()["membership"]
    assert provider_membership["side"] == "provider"
    assert added.json()["organization"]["kinds"] == ["customer", "provider"]

    ambiguous = await client.get("/memberships", headers=auth(token, org_id))
    assert ambiguous.status_code == 409
    assert ambiguous.json()["error"]["code"] == "MEMBERSHIP_AMBIGUOUS"

    me = (await client.get("/me", headers=auth(token))).json()
    assert sorted(m["side"] for m in me["memberships"]) == ["customer", "provider"]
    assert me["organizations"] == [
        {"id": org_id, "name": "Двойная", "kinds": ["customer", "provider"]}
    ]
    customer_membership = next(m for m in me["memberships"] if m["side"] == "customer")

    as_provider = {"Authorization": f"Bearer {token}", "X-Membership-Id": provider_membership["id"]}
    as_customer = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org_id,
        "X-Membership-Id": customer_membership["id"],
    }
    provider_members = (await client.get("/memberships", headers=as_provider)).json()["items"]
    assert [m["id"] for m in provider_members] == [provider_membership["id"]]
    customer_members = (await client.get("/memberships", headers=as_customer)).json()["items"]
    assert [m["id"] for m in customer_members] == [customer_membership["id"]]

    assert (await client.get("/locations", headers=as_provider)).status_code == 403

    renamed = await client.patch(
        f"/organizations/{org_id}",
        json={"name": "Двойная и новая", "contact_phone": "+79990000001"},
        headers={**as_provider, **idem("iso-dual-patch")},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Двойная и новая"


async def test_patch_foreign_organization_is_not_found(client: AsyncClient) -> None:
    mine = await _org("Моя", "iso-patch-mine")
    other = await _org("Чужая", "iso-patch-other")

    response = await client.patch(
        f"/organizations/{other.organization_id}",
        json={"name": "Захват"},
        headers={**auth(mine.token, mine.organization_id), **idem("iso-patch")},
    )
    assert response.status_code == 404
