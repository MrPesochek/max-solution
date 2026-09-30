from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.operator import attachments, reputation_router
from app.adapters.operator.deps import CurrentOperator, IdemKey
from app.adapters.operator.schemas import (
    GrantOperatorBody,
    OperatorBindingView,
    Page,
    PlatformRoleView,
    ProfileStatusBody,
    ReopenVerificationBody,
    RevokeBody,
    VerificationDecisionBody,
    WarrantyAuthorizationBody,
    page_of,
    to_operator_binding_view,
)
from app.core import ids
from app.modules.identity import api as identity
from app.modules.integration import api as integration
from app.modules.integration.api import DeliveryPageView, DeliveryView
from app.modules.providers import api as providers
from app.modules.providers.api import ProviderProfileView
from app.modules.requests import api as requests_api
from app.modules.requests.api import SupervisedAssignmentView
from app.modules.trust import api as trust
from app.modules.trust.api import (
    ServiceBindingView,
    VerificationCaseOperatorView,
    VerificationCaseView,
    VerificationInformationSubmittedView,
    WarrantyAuthorizationView,
)

OPERATOR_PREFIX = "/operator-api/v1"

router = APIRouter(tags=["operator"], responses=STANDARD_ERROR_RESPONSES)


@router.get("/verification-cases", response_model=Page[VerificationCaseOperatorView])
async def list_verification_cases(
    operator: CurrentOperator,
    decision: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[VerificationCaseOperatorView]:
    items, next_cursor = await trust.list_verification_queue(
        operator,
        decision=decision,
        cursor=ids.decode("verification_case", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "verification_case", next_cursor)


@router.get("/verification-cases/{case_id}", response_model=VerificationCaseOperatorView)
async def get_verification_case(
    operator: CurrentOperator, case_id: str
) -> VerificationCaseOperatorView:
    return await trust.get_verification_case(operator, ids.decode("verification_case", case_id))


@router.post("/verification-cases/{case_id}/decision", response_model=VerificationCaseView)
async def decide_verification_case(
    operator: CurrentOperator, case_id: str, body: VerificationDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = trust.VerificationDecisionData(
        decision=body.decision,
        reason=body.reason,
        source=body.source,
        expires_at=body.expires_at,
        is_demo=body.is_demo,
    )
    idem = make_idempotency(
        idem_key, f"POST /verification-cases/{case_id}/decision", body.model_dump(mode="json")
    )
    result = await trust.decide_verification_case(operator, case_id, data, idem=idem)
    return result.body


@router.get("/provider-profiles", response_model=Page[ProviderProfileView])
async def list_provider_profiles(
    operator: CurrentOperator,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ProviderProfileView]:
    items, next_cursor = await providers.list_profiles_for_operator(
        operator,
        status=status,
        cursor=ids.decode("provider_profile", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "provider_profile", next_cursor)


@router.post("/provider-profiles/{organization_id}/suspend", response_model=ProviderProfileView)
async def suspend_provider(
    operator: CurrentOperator, organization_id: str, body: ProfileStatusBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /provider-profiles/{organization_id}/suspend", body.model_dump()
    )
    result = await trust.suspend_provider(operator, organization_id, body.reason, idem=idem)
    return result.body


@router.post("/provider-profiles/{organization_id}/reinstate", response_model=ProviderProfileView)
async def reinstate_provider(
    operator: CurrentOperator, organization_id: str, body: ProfileStatusBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /provider-profiles/{organization_id}/reinstate", body.model_dump()
    )
    result = await trust.reinstate_provider(operator, organization_id, body.reason, idem=idem)
    return result.body


@router.post(
    "/provider-profiles/{organization_id}/reopen-verification",
    response_model=VerificationInformationSubmittedView,
)
async def reopen_verification(
    operator: CurrentOperator,
    organization_id: str,
    body: ReopenVerificationBody,
    idem_key: IdemKey,
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key,
        f"POST /provider-profiles/{organization_id}/reopen-verification",
        body.model_dump(),
    )
    result = await trust.reopen_verification(
        operator,
        organization_id,
        body.check_kind,
        body.reason,
        compromise=body.compromise,
        idem=idem,
    )
    return result.body


@router.get("/supervised-assignments", response_model=list[SupervisedAssignmentView])
async def list_supervised_assignments(
    operator: CurrentOperator,
) -> list[SupervisedAssignmentView]:
    return await requests_api.supervised_assignments(operator)


@router.get("/deliveries", response_model=DeliveryPageView)
async def list_deliveries(
    operator: CurrentOperator,
    organization_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DeliveryPageView:
    return await integration.list_deliveries(
        ids.decode("organization", organization_id), cursor=cursor, limit=limit
    )


@router.post("/deliveries/{delivery_id}/redeliver", response_model=DeliveryView)
async def redeliver(
    operator: CurrentOperator, delivery_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /deliveries/{delivery_id}/redeliver", {})
    result = await integration.redeliver(operator, delivery_id, idem=idem)
    return result.body


@router.get("/warranty-authorizations", response_model=Page[WarrantyAuthorizationView])
async def list_warranty_authorizations(
    operator: CurrentOperator,
    provider_organization_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[WarrantyAuthorizationView]:
    items, next_cursor = await trust.list_warranty_authorizations(
        operator,
        provider_org_id=(
            ids.decode("organization", provider_organization_id)
            if provider_organization_id
            else None
        ),
        cursor=ids.decode("warranty_authorization", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "warranty_authorization", next_cursor)


@router.post("/warranty-authorizations", response_model=WarrantyAuthorizationView, status_code=201)
async def create_warranty_authorization(
    operator: CurrentOperator, body: WarrantyAuthorizationBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = trust.WarrantyAuthorizationData(
        provider_organization_id=body.provider_organization_id,
        guarantor_kind=body.guarantor_kind,
        source=body.source,
        reason=body.reason,
        guarantor_name=body.guarantor_name,
        guarantor_organization_id=body.guarantor_organization_id,
        equipment_category_id=body.equipment_category_id,
        brands=body.brands,
        city_id=body.city_id,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        is_demo=body.is_demo,
    )
    idem = make_idempotency(idem_key, "POST /warranty-authorizations", body.model_dump(mode="json"))
    result = await trust.create_warranty_authorization(operator, data, idem=idem)
    return result.body


@router.post(
    "/warranty-authorizations/{authorization_id}/revoke", response_model=WarrantyAuthorizationView
)
async def revoke_warranty_authorization(
    operator: CurrentOperator, authorization_id: str, body: RevokeBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /warranty-authorizations/{authorization_id}/revoke", body.model_dump()
    )
    result = await trust.revoke_warranty_authorization(
        operator, authorization_id, body.reason, idem=idem
    )
    return result.body


@router.get("/service-bindings", response_model=Page[OperatorBindingView])
async def list_bindings(
    operator: CurrentOperator,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[OperatorBindingView]:
    rows, next_cursor = await trust.list_operator_bindings(
        operator,
        status=status,
        cursor=ids.decode("service_binding", cursor) if cursor else None,
        limit=limit,
    )
    return page_of([to_operator_binding_view(row) for row in rows], "service_binding", next_cursor)


@router.post("/service-bindings/{binding_id}/revoke", response_model=ServiceBindingView)
async def revoke_binding(
    operator: CurrentOperator, binding_id: str, body: RevokeBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /service-bindings/{binding_id}/revoke", body.model_dump()
    )
    result = await trust.revoke_binding(operator, binding_id, body.reason, idem=idem)
    return result.body


@router.post("/platform-roles/operator", response_model=PlatformRoleView)
async def grant_operator(
    operator: CurrentOperator, body: GrantOperatorBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /platform-roles/operator", body.model_dump())
    result = await identity.grant_operator(operator, body.max_user_id, idem=idem)
    return result.body


@router.post("/platform-roles/operator/revoke", response_model=PlatformRoleView)
async def revoke_operator(
    operator: CurrentOperator, body: GrantOperatorBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /platform-roles/operator/revoke", body.model_dump())
    result = await identity.revoke_operator(operator, body.max_user_id, idem=idem)
    return result.body


def build_operator_router() -> APIRouter:
    operator_router = APIRouter(prefix=OPERATOR_PREFIX)
    operator_router.include_router(router)
    operator_router.include_router(attachments.router)
    operator_router.include_router(reputation_router.router)
    return operator_router
