from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import Idem, MessageWrite, RequestsRead, RequestsWrite
from app.adapters.integration_api.schemas import (
    AcceptRequestBody,
    CancellationResponseBody,
    CompleteWorkBody,
    DeclineRequestBody,
    EnRouteBody,
    ExternalReferenceBody,
    FieldWorkerBody,
    MessageCreateBody,
    Page,
    RepairQuoteBody,
    StartWorkBody,
    VisitProposalBody,
    WarrantyDecisionBody,
    WithdrawAssignmentBody,
)
from app.core import ids
from app.modules.requests import api as requests_api
from app.modules.requests.api import (
    MessageView,
    RepairQuoteInput,
    RepairQuoteItemInput,
    RequestFormerProviderView,
    RequestListItemView,
    RequestProviderView,
    VisitProposalInput,
)
from app.modules.requests.views import RepairQuoteView, VisitProposalView

router = APIRouter(prefix="/requests", tags=["requests"], responses=STANDARD_ERROR_RESPONSES)


@router.get("", response_model=Page[RequestListItemView])
async def list_requests(
    actor: RequestsRead,
    status: Annotated[list[str] | None, Query()] = None,
    assignment_state: Annotated[list[str] | None, Query()] = None,
    updated_since: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[RequestListItemView]:
    items, next_cursor = await requests_api.list_requests(
        actor,
        statuses=status,
        assignment_states=assignment_state,
        updated_since=updated_since,
        cursor=cursor,
        limit=limit,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/{request_id}",
    response_model=RequestProviderView | RequestFormerProviderView,
)
async def get_request(actor: RequestsRead, request_id: str) -> Any:
    return await requests_api.get_request(actor, ids.decode("request", request_id))


@router.post(
    "/{request_id}/external-reference",
    response_model=RequestProviderView,
)
async def set_external_reference(
    actor: RequestsWrite, request_id: str, body: ExternalReferenceBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.set_external_reference(
        actor,
        ids.decode("request", request_id),
        external_id=body.external_id,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/accept",
    response_model=RequestProviderView,
    description=(
        "Подтверждение назначения, в том числе выбранного на бирже (offer.select) — "
        "по scope заявок, а не биржи."
    ),
)
async def accept_request(
    actor: RequestsWrite, request_id: str, body: AcceptRequestBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.accept_assignment(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/decline",
    response_model=RequestProviderView,
)
async def decline_request(
    actor: RequestsWrite, request_id: str, body: DeclineRequestBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.decline_assignment(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/withdraw",
    response_model=RequestProviderView,
    description="D2: отказ исполнителя после принятия назначения.",
)
async def withdraw_assignment(
    actor: RequestsWrite, request_id: str, body: WithdrawAssignmentBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.withdraw_assignment(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.get(
    "/{request_id}/messages",
    response_model=Page[MessageView],
)
async def list_messages(
    actor: RequestsRead,
    request_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[MessageView]:
    items, next_cursor = await requests_api.list_messages(
        actor, ids.decode("request", request_id), cursor=cursor, limit=limit
    )
    return Page(items=items, next_cursor=next_cursor)


@router.post(
    "/{request_id}/messages",
    response_model=MessageView,
    status_code=201,
)
async def post_message(
    actor: MessageWrite, request_id: str, body: MessageCreateBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.post_message(
        actor,
        ids.decode("request", request_id),
        body=body.body,
        assignment_id=ids.decode("assignment", body.assignment_id) if body.assignment_id else None,
        thread_provider_org_id=(
            ids.decode("organization", body.thread_provider_id) if body.thread_provider_id else None
        ),
        expected_version=body.expected_version,
        author_label=body.author_label,
        idem=idem.of(body),
    )
    return result.body


@router.get(
    "/{request_id}/visit-proposals",
    response_model=list[VisitProposalView],
)
async def list_visit_proposals(actor: RequestsRead, request_id: str) -> list[dict[str, Any]]:
    return await requests_api.list_visit_proposals(actor, ids.decode("request", request_id))


@router.post(
    "/{request_id}/visit-proposals",
    response_model=RequestProviderView,
    status_code=201,
)
async def propose_visit(
    actor: RequestsWrite, request_id: str, body: VisitProposalBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.propose_visit(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        data=VisitProposalInput(
            visit_window_start=body.visit_window_start,
            visit_window_end=body.visit_window_end,
            amount_minor=body.amount_minor,
            currency=body.currency,
            vat_mode=body.vat_mode,
            zero_cost_reason=body.zero_cost_reason,
            scope_description=body.scope_description,
            comment=body.comment,
            access_requirements=body.access_requirements,
            valid_until=body.valid_until,
        ),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.get(
    "/{request_id}/repair-quotes",
    response_model=list[RepairQuoteView],
)
async def list_repair_quotes(actor: RequestsRead, request_id: str) -> list[dict[str, Any]]:
    return await requests_api.list_repair_quotes(actor, ids.decode("request", request_id))


@router.post(
    "/{request_id}/repair-quotes",
    response_model=RequestProviderView,
    status_code=201,
)
async def create_repair_quote(
    actor: RequestsWrite, request_id: str, body: RepairQuoteBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.create_repair_quote(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        data=RepairQuoteInput(
            description_of_work=body.description_of_work,
            items=(
                tuple(RepairQuoteItemInput(i.title, i.amount_minor) for i in body.items)
                if body.items is not None
                else None
            ),
            amount_minor=body.amount_minor,
            currency=body.currency,
            vat_mode=body.vat_mode,
            zero_cost_reason=body.zero_cost_reason,
            valid_until=body.valid_until,
            warranty_terms=body.warranty_terms,
        ),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/start-work",
    response_model=RequestProviderView,
)
async def start_work(
    actor: RequestsWrite, request_id: str, body: StartWorkBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.start_work(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/en-route",
    response_model=RequestProviderView,
    description=(
        "Отметка «мастер выехал»: статус заявки остаётся `scheduled`, в назначении "
        "появляется `en_route_at`. Повторная отметка — `409 ALREADY_EN_ROUTE`."
    ),
)
async def mark_en_route(
    actor: RequestsWrite, request_id: str, body: EnRouteBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.mark_en_route(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/complete",
    response_model=RequestProviderView,
)
async def complete_work(
    actor: RequestsWrite, request_id: str, body: CompleteWorkBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.report_completion(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        outcome=body.outcome,
        summary=body.summary,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/cancellation-response",
    response_model=RequestProviderView,
)
async def respond_cancellation(
    actor: RequestsWrite, request_id: str, body: CancellationResponseBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.respond_cancellation(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        cancellation_id=ids.decode("cancellation", body.cancellation_id),
        decision=body.decision,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/warranty-decision",
    response_model=RequestProviderView,
)
async def warranty_decision(
    actor: RequestsWrite, request_id: str, body: WarrantyDecisionBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.set_warranty_decision(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        decision=body.decision,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/{request_id}/field-worker",
    response_model=RequestProviderView,
)
async def set_field_worker(
    actor: RequestsWrite, request_id: str, body: FieldWorkerBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.set_field_worker(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        membership_id=ids.decode("membership", body.membership_id) if body.membership_id else None,
        display_name=body.display_name,
        contact_phone=body.contact_phone,
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body
