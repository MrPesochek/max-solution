from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.app_api.deps import CurrentSession
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.operator.deps import IdemKey
from app.adapters.operator.schemas import Page, VerificationDecisionBody, page_of
from app.core import ids
from app.core.actor import OperatorActor
from app.core.errors import Forbidden, NotFound
from app.db import session as db_session
from app.db.models import Membership, Organization, User
from app.demo.seed import DEMO_ORG_IDS, ORG_CUSTOMER, ORG_PROVIDER
from app.infra.config import get_settings
from app.modules.identity import api as identity
from app.modules.identity.views import MembershipView
from app.modules.trust import api as trust

router = APIRouter(tags=["showcase"], responses=STANDARD_ERROR_RESPONSES)


class ShowcaseStatus(BaseModel):
    enabled: bool


class ShowcaseJoin(BaseModel):
    side: Literal["customer", "provider"]


@router.get("/showcase", response_model=ShowcaseStatus)
async def status(session: CurrentSession) -> ShowcaseStatus:
    return ShowcaseStatus(enabled=get_settings().demo_showcase_enabled)


@router.post("/showcase/join", response_model=MembershipView)
async def join(session: CurrentSession, body: ShowcaseJoin) -> MembershipView:
    if not get_settings().demo_showcase_enabled:
        raise NotFound()
    organization_id = ORG_CUSTOMER if body.side == "customer" else ORG_PROVIDER
    role = "customer_manager" if body.side == "customer" else "provider_dispatcher"
    async with db_session.transaction() as db:
        organization = await db.get(Organization, organization_id)
        if organization is None:
            raise NotFound("Демонстрационные данные ещё не подготовлены")
        await db.execute(select(User).where(User.id == session.user_id).with_for_update())
        await db.execute(
            insert(Membership)
            .values(
                user_id=session.user_id,
                organization_id=organization_id,
                role=role,
                status="active",
            )
            .on_conflict_do_nothing()
        )
    memberships = await identity.list_user_memberships(session.user_id)
    public_id = ids.encode("organization", organization_id)
    membership = next((m for m in memberships if m.organization.id == public_id), None)
    if membership is None:
        raise Forbidden("Доступ к демонстрации отозван")
    return membership


@router.get("/showcase/verification-cases", response_model=Page[trust.VerificationCaseOperatorView])
async def verification_queue(
    session: CurrentSession,
    decision: Literal["pending", "approved", "rejected", "needs_information"] | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[trust.VerificationCaseOperatorView]:
    if not get_settings().demo_showcase_enabled:
        raise NotFound()
    rows, next_cursor = await trust.list_verification_queue(
        OperatorActor(user_id=session.user_id),
        decision=decision,
        cursor=ids.decode("verification_case", cursor) if cursor else None,
        limit=limit,
        organization_ids=DEMO_ORG_IDS,
    )
    return page_of(rows, "verification_case", next_cursor)


@router.post(
    "/showcase/verification-cases/{case_id}/decision",
    response_model=trust.VerificationCaseView,
)
async def verification_decision(
    session: CurrentSession, case_id: str, body: VerificationDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    if not get_settings().demo_showcase_enabled:
        raise NotFound()
    result = await trust.decide_verification_case(
        OperatorActor(user_id=session.user_id),
        case_id,
        trust.VerificationDecisionData(
            decision=body.decision,
            reason=body.reason,
            source=body.source,
            expires_at=body.expires_at,
            is_demo=True,
        ),
        idem=make_idempotency(
            idem_key,
            f"POST /showcase/verification-cases/{case_id}/decision",
            body.model_dump(mode="json"),
        ),
        organization_ids=DEMO_ORG_IDS,
    )
    return result.body
