from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core import ids
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import ProviderProfile, ProviderRatingAggregate
from app.modules.providers import api as providers
from app.modules.reputation import api as reputation
from tests.providers.conftest import auth, idem_header
from tests.support import idem, make_operator, make_provider, org_id, session_token

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_own_profile_shows_rating_and_visit_price(client: AsyncClient) -> None:
    provider = await make_provider("own-extras")
    async with db_session.transaction() as session:
        session.add(
            ProviderRatingAggregate(
                provider_org_id=provider.organization_id,
                average_rating=Decimal("4.8"),
                unique_reviewer_orgs_count=5,
                published_reviews_count=9,
            )
        )
    headers = auth(await session_token(provider.admin), org_id(provider.admin))

    patched = await client.patch(
        "/provider-profile",
        headers={**headers, **idem_header("own-extras-1")},
        json={
            "visit_price_from_minor": 250000,
            "contact_name": "Иван Петров",
            "representative_position": "Генеральный директор",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["visit_price_from_minor"] == 250000
    assert body["contact_name"] == "Иван Петров"
    assert body["representative_position"] == "Генеральный директор"
    assert (body["rating"], body["reviews_count"], body["unique_customers"]) == (4.8, 9, 5)
    assert body["appeal"] is None

    negative = await client.patch(
        "/provider-profile",
        headers={**headers, **idem_header("own-extras-2")},
        json={"visit_price_from_minor": -1},
    )
    assert negative.status_code == 422

    cleared = await client.patch(
        "/provider-profile",
        headers={**headers, **idem_header("own-extras-3")},
        json={"visit_price_from_minor": None},
    )
    assert cleared.json()["visit_price_from_minor"] is None


async def test_registration_keeps_position_apart_from_contact_name(client: AsyncClient) -> None:
    provider = await make_provider("reg-pos")
    headers = {"Authorization": f"Bearer {await session_token(provider.admin)}"}
    created = await client.post(
        "/organizations",
        headers={**headers, **idem_header("reg-pos-1")},
        json={
            "name": "Сервис Север",
            "kind": "provider",
            "contact_phone": "+79990000001",
            "contact_name": "Анна Смирнова",
            "representative_position": "Руководитель сервиса",
        },
    )
    assert created.status_code == 201, created.text
    organization = created.json()["organization"]
    assert organization["contact_name"] == "Анна Смирнова"
    assert organization["representative_position"] == "Руководитель сервиса"


async def test_appeal_of_suspension_goes_to_operator_queue(client: AsyncClient) -> None:
    provider = await make_provider("appeal", status="suspended")
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.id == provider.profile_id)
            .values(status_reason="Жалобы клиентов")
        )
    headers = auth(await session_token(provider.admin), org_id(provider.admin))

    filed = await client.post(
        "/provider-profile/appeal",
        headers={**headers, **idem_header("appeal-1")},
        json={"text": "Жалобы урегулированы, прикладываем акты"},
    )
    assert filed.status_code == 201, filed.text
    assert filed.json()["appeal_status"] == "pending"

    again = await client.post(
        "/provider-profile/appeal",
        headers={**headers, **idem_header("appeal-2")},
        json={"text": "Повторно"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PROFILE_APPEAL_ALREADY_OPEN"

    profile = (await client.get("/provider-profile", headers=headers)).json()
    assert profile["appeal"]["status"] == "pending"
    assert profile["appeal"]["decision"] is None

    operator = await make_operator("appeal-op")
    queue, _ = await reputation.list_moderation_case_queue(
        operator, subject_type="provider_profile", kind="appeal"
    )
    assert len(queue) == 1
    assert queue[0].evidence["profile_status_at_filing"] == "suspended"
    assert queue[0].evidence["status_reason_at_filing"] == "Жалобы клиентов"
    assert await reputation.list_moderation_case_queue(operator, kind="complaint") == ([], None)

    await reputation.decide_moderation_case(
        operator,
        ids.decode("moderation_case", queue[0].id),
        "rejected",
        "Нарушения повторяются",
        idem=idem("appeal-decide"),
    )
    own = await providers.get_own_profile(scope_of(provider.admin))
    assert own.appeal is not None
    assert (own.appeal.status, own.appeal.decision) == ("resolved", "rejected")
    assert own.appeal.decision_reason == "Нарушения повторяются"


async def test_active_profile_cannot_be_appealed(client: AsyncClient) -> None:
    provider = await make_provider("appeal-active", status="active")
    headers = auth(await session_token(provider.admin), org_id(provider.admin))
    response = await client.post(
        "/provider-profile/appeal",
        headers={**headers, **idem_header("appeal-active")},
        json={"text": "Просто так"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPEAL_NOT_ALLOWED"


async def test_dispatcher_cannot_appeal(client: AsyncClient) -> None:
    provider = await make_provider("appeal-disp", status="rejected")
    headers = auth(await session_token(provider.dispatcher), org_id(provider.dispatcher))
    response = await client.post(
        "/provider-profile/appeal",
        headers={**headers, **idem_header("appeal-disp")},
        json={"text": "Не согласны"},
    )
    assert response.status_code == 403
