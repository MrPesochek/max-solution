import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import (
    AssignmentAcceptBody,
    AssignmentCancellationResponseBody,
    AssignmentDeclineBody,
    AssignmentFieldWorkerBody,
    AssignmentMarkEnRouteBody,
    AssignmentProposeVisitBody,
    AssignmentRepairQuoteBody,
    AssignmentReportCompletionBody,
    AssignmentStartWorkBody,
    AssignmentWarrantyDecisionBody,
    AssignmentWithdrawBody,
    DialogMessageBody,
    Page,
    RequestApprovalBody,
    RequestCancelDraftBody,
    RequestCancellationBody,
    RequestCancellationIdBody,
    RequestDraftCreateBody,
    RequestDraftUpdateBody,
    RequestFollowupBody,
    RequestMessageBody,
    RequestPublicCardBody,
    RequestPublicCardPreviewBody,
    RequestQuoteDecisionBody,
    RequestRejectCompletionBody,
    RequestReturnToDraftBody,
    RequestRevokeAssignmentBody,
    RequestSelectOfferBody,
    RequestSubmitToOwnServiceBody,
    RequestUpdateDetailsBody,
    RequestVisitDecisionBody,
    VersionOnlyBody,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.patch import field_or_unset
from app.core import ids
from app.modules.requests import api as requests_api
from app.modules.requests.api import (
    MessagesReadView,
    MessageView,
    OfferView,
    PendingApprovalItemView,
    PublicCardInput,
    RepairQuoteInput,
    RepairQuoteItemInput,
    RequestCustomerView,
    RequestEventView,
    RequestFormerProviderView,
    RequestListItemView,
    RequestProviderView,
    VisitProposalInput,
)
from app.modules.requests.views import PublicCardPreviewView, RepairQuoteView, VisitProposalView

router = APIRouter(prefix="/requests", tags=["requests"], responses=STANDARD_ERROR_RESPONSES)

RequestView = RequestCustomerView | RequestProviderView | RequestFormerProviderView

MessageDirectionQuery = Annotated[
    Literal["forward", "backward"],
    Query(
        description=(
            "forward — от старых к новым; backward — сначала свежие, курсор ведёт к более "
            "ранним. Внутри страницы порядок хронологический."
        )
    ),
]


def _rid(request_id: str) -> uuid.UUID:
    return ids.decode("request", request_id)


def _public_card_input(body: RequestPublicCardPreviewBody) -> PublicCardInput:
    return PublicCardInput(
        published_description=body.published_description,
        district_id=ids.decode("district", body.district_id) if body.district_id else None,
        attachment_ids=tuple(ids.decode("attachment", a) for a in body.attachment_ids),
        confirm_sensitive=body.confirm_sensitive,
    )


@router.get("", response_model=Page[RequestListItemView])
async def list_requests(
    scope: Scope,
    actor: OrgActor,
    status: Annotated[list[str] | None, Query()] = None,
    location_id: str | None = None,
    equipment_id: Annotated[
        str | None, Query(description="История единицы техники: заявки только по ней.")
    ] = None,
    active: bool | None = None,
    assignment_state: Annotated[list[str] | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[RequestListItemView]:
    items, next_cursor = await requests_api.list_requests(
        actor,
        statuses=status,
        location_id=ids.decode("location", location_id) if location_id else None,
        equipment_id=ids.decode("equipment", equipment_id) if equipment_id else None,
        active=active,
        assignment_states=assignment_state,
        cursor=cursor,
        limit=limit,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get("/pending-approvals", response_model=list[PendingApprovalItemView])
async def pending_approvals(actor: OrgActor) -> list[PendingApprovalItemView]:
    """Только руководитель заказчика (I10); до `/{request_id}` — иначе перехватит его."""
    return await requests_api.pending_approvals(actor)


@router.get("/{request_id}", response_model=RequestView)
async def get_request(actor: OrgActor, request_id: str) -> Any:
    return await requests_api.get_request(actor, _rid(request_id))


@router.get("/{request_id}/history", response_model=Page[RequestEventView])
async def request_history(
    actor: OrgActor,
    request_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[RequestEventView]:
    items, next_cursor = await requests_api.request_history(
        actor, _rid(request_id), cursor=cursor, limit=limit
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get("/{request_id}/offers", response_model=list[OfferView])
async def list_offers(actor: OrgActor, request_id: str) -> list[OfferView]:
    return await requests_api.list_offers(actor, _rid(request_id))


@router.get("/{request_id}/visit-proposals", response_model=list[VisitProposalView])
async def list_visit_proposals(actor: OrgActor, request_id: str) -> list[dict[str, Any]]:
    return await requests_api.list_visit_proposals(actor, _rid(request_id))


@router.get("/{request_id}/repair-quotes", response_model=list[RepairQuoteView])
async def list_repair_quotes(actor: OrgActor, request_id: str) -> list[dict[str, Any]]:
    return await requests_api.list_repair_quotes(actor, _rid(request_id))


@router.get("/{request_id}/messages", response_model=Page[MessageView])
async def list_messages(
    actor: OrgActor,
    request_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    direction: MessageDirectionQuery = "forward",
) -> Page[MessageView]:
    items, next_cursor = await requests_api.list_messages(
        actor, _rid(request_id), cursor=cursor, limit=limit, direction=direction
    )
    return Page(items=items, next_cursor=next_cursor)


@router.post("/{request_id}/messages", response_model=MessageView, status_code=201)
async def post_message(
    actor: OrgActor, request_id: str, body: RequestMessageBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /requests/{request_id}/messages", body.model_dump(mode="json")
    )
    result = await requests_api.post_message(
        actor,
        _rid(request_id),
        body=body.body,
        assignment_id=ids.decode("assignment", body.assignment_id) if body.assignment_id else None,
        thread_provider_org_id=(
            ids.decode("organization", body.thread_provider_id) if body.thread_provider_id else None
        ),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.get("/{request_id}/offers/{offer_id}/messages", response_model=Page[MessageView])
async def list_offer_messages(
    actor: OrgActor,
    request_id: str,
    offer_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    direction: MessageDirectionQuery = "forward",
) -> Page[MessageView]:
    """S3.5: вопросы автора отклика и ответы заказчика; видят только они."""
    items, next_cursor = await requests_api.list_dialog_messages(
        actor,
        _rid(request_id),
        offer_id=ids.decode("offer", offer_id),
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.post(
    "/{request_id}/offers/{offer_id}/messages", response_model=MessageView, status_code=201
)
async def post_offer_message(
    actor: OrgActor, request_id: str, offer_id: str, body: DialogMessageBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key,
        f"POST /requests/{request_id}/offers/{offer_id}/messages",
        body.model_dump(mode="json"),
    )
    result = await requests_api.post_dialog_message(
        actor,
        _rid(request_id),
        body=body.body,
        offer_id=ids.decode("offer", offer_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/messages/read", response_model=MessagesReadView)
async def mark_messages_read(actor: OrgActor, request_id: str) -> dict[str, Any]:
    """Прочитано до последнего видимого сообщения; повтор безопасен без Idempotency-Key."""
    result = await requests_api.mark_messages_read(actor, _rid(request_id))
    return result.body


@router.post("", response_model=RequestCustomerView, status_code=201)
async def create_draft(
    actor: OrgActor, body: RequestDraftCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /requests", body.model_dump(mode="json"))
    result = await requests_api.create_draft(
        actor,
        equipment_id=ids.decode("equipment", body.equipment_id),
        route=body.route,
        urgency=body.urgency,
        symptom_description=body.symptom_description,
        error_code=body.error_code,
        idem=idem,
    )
    return result.body


@router.patch("/{request_id}", response_model=RequestCustomerView)
async def update_draft(
    actor: OrgActor, request_id: str, body: RequestDraftUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"PATCH /requests/{request_id}", body.model_dump(mode="json"))
    equipment_public_id = field_or_unset(body, "equipment_id")
    result = await requests_api.update_draft(
        actor,
        _rid(request_id),
        equipment_id=(
            ids.decode("equipment", equipment_public_id)
            if isinstance(equipment_public_id, str)
            else equipment_public_id
        ),
        urgency=field_or_unset(body, "urgency"),
        symptom_description=field_or_unset(body, "symptom_description"),
        error_code=field_or_unset(body, "error_code"),
        photos_incomplete=field_or_unset(body, "photos_incomplete"),
        photos_incomplete_reason=field_or_unset(body, "photos_incomplete_reason"),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


def _action(name: str, request_id: str) -> str:
    return f"POST /requests/{request_id}/actions/{name}"


@router.post("/{request_id}/actions/submit-to-own-service", response_model=RequestCustomerView)
async def submit_to_own_service(
    actor: OrgActor, request_id: str, body: RequestSubmitToOwnServiceBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("submit-to-own-service", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.submit_to_own_service(
        actor,
        _rid(request_id),
        photos_incomplete=body.photos_incomplete,
        photos_incomplete_reason=body.photos_incomplete_reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/request-approval", response_model=RequestCustomerView)
async def request_approval(
    actor: OrgActor, request_id: str, body: RequestApprovalBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("request-approval", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.request_approval(
        actor,
        _rid(request_id),
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/return-to-draft", response_model=RequestCustomerView)
async def return_to_draft(
    actor: OrgActor, request_id: str, body: RequestReturnToDraftBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("return-to-draft", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.return_to_draft(
        actor,
        _rid(request_id),
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/cancel-draft", response_model=RequestCustomerView)
async def cancel_draft(
    actor: OrgActor, request_id: str, body: RequestCancelDraftBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("cancel-draft", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.cancel_draft(
        actor,
        _rid(request_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/revoke-assignment", response_model=RequestCustomerView)
async def revoke_assignment(
    actor: OrgActor, request_id: str, body: RequestRevokeAssignmentBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("revoke-assignment", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.revoke_pending_assignment(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/preview-public-card", response_model=PublicCardPreviewView)
async def preview_public_card(
    actor: OrgActor, request_id: str, body: RequestPublicCardPreviewBody
) -> PublicCardPreviewView:
    """Чтение с параметрами: ничего не публикует и не требует идемпотентности."""
    return await requests_api.preview_public_card(
        actor, _rid(request_id), data=_public_card_input(body)
    )


@router.post("/{request_id}/actions/publish-search", response_model=RequestCustomerView)
async def publish_search(
    actor: OrgActor, request_id: str, body: RequestPublicCardBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("publish-search", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.publish_search(
        actor,
        _rid(request_id),
        data=_public_card_input(body),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/select-offer", response_model=RequestCustomerView)
async def select_offer(
    actor: OrgActor, request_id: str, body: RequestSelectOfferBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("select-offer", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.select_offer(
        actor,
        _rid(request_id),
        offer_id=ids.decode("offer", body.offer_id),
        offer_version=body.offer_version,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/approve-visit-proposal", response_model=RequestCustomerView)
async def approve_visit_proposal(
    actor: OrgActor, request_id: str, body: RequestVisitDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("approve-visit-proposal", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.approve_visit_proposal(
        actor,
        _rid(request_id),
        proposal_id=ids.decode("visit_proposal", body.proposal_id),
        proposal_version=body.proposal_version,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/reject-visit-proposal", response_model=RequestCustomerView)
async def reject_visit_proposal(
    actor: OrgActor, request_id: str, body: RequestVisitDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("reject-visit-proposal", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.reject_visit_proposal(
        actor,
        _rid(request_id),
        proposal_id=ids.decode("visit_proposal", body.proposal_id),
        proposal_version=body.proposal_version,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/approve-repair-quote", response_model=RequestCustomerView)
async def approve_repair_quote(
    actor: OrgActor, request_id: str, body: RequestQuoteDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("approve-repair-quote", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.approve_repair_quote(
        actor,
        _rid(request_id),
        quote_id=ids.decode("repair_quote", body.quote_id),
        quote_version=body.quote_version,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/reject-repair-quote", response_model=RequestCustomerView)
async def reject_repair_quote(
    actor: OrgActor, request_id: str, body: RequestQuoteDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("reject-repair-quote", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.reject_repair_quote(
        actor,
        _rid(request_id),
        quote_id=ids.decode("repair_quote", body.quote_id),
        quote_version=body.quote_version,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/request-cancellation", response_model=RequestCustomerView)
async def request_cancellation(
    actor: OrgActor, request_id: str, body: RequestCancellationBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("request-cancellation", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.request_cancellation(
        actor,
        _rid(request_id),
        target=body.target,
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/withdraw-cancellation", response_model=RequestCustomerView)
async def withdraw_cancellation(
    actor: OrgActor, request_id: str, body: RequestCancellationIdBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("withdraw-cancellation", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.withdraw_cancellation(
        actor,
        _rid(request_id),
        cancellation_id=ids.decode("cancellation", body.cancellation_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/force-cancellation", response_model=RequestCustomerView)
async def force_cancellation(
    actor: OrgActor, request_id: str, body: RequestCancellationIdBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("force-cancellation", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.force_cancellation(
        actor,
        _rid(request_id),
        cancellation_id=ids.decode("cancellation", body.cancellation_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/confirm-completion", response_model=RequestCustomerView)
async def confirm_completion(
    actor: OrgActor, request_id: str, body: VersionOnlyBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("confirm-completion", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.confirm_completion(
        actor, _rid(request_id), expected_version=body.expected_version, idem=idem
    )
    return result.body


@router.post("/{request_id}/actions/reject-completion", response_model=RequestCustomerView)
async def reject_completion(
    actor: OrgActor, request_id: str, body: RequestRejectCompletionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("reject-completion", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.reject_completion(
        actor,
        _rid(request_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/update-details", response_model=RequestCustomerView)
async def update_details(
    actor: OrgActor, request_id: str, body: RequestUpdateDetailsBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("update-details", request_id), body.model_dump(mode="json")
    )
    district_public_id = field_or_unset(body, "district_id")
    result = await requests_api.update_request_details(
        actor,
        _rid(request_id),
        symptom_description=field_or_unset(body, "symptom_description"),
        urgency=field_or_unset(body, "urgency"),
        district_id=(
            ids.decode("district", district_public_id)
            if isinstance(district_public_id, str)
            else district_public_id
        ),
        published_description=field_or_unset(body, "published_description"),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post(
    "/{request_id}/actions/create-followup", response_model=RequestCustomerView, status_code=201
)
async def create_followup(
    actor: OrgActor, request_id: str, body: RequestFollowupBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("create-followup", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.create_followup_request(
        actor, _rid(request_id), urgency=body.urgency, idem=idem
    )
    return result.body


@router.post("/{request_id}/actions/accept", response_model=RequestProviderView)
async def accept(
    actor: OrgActor, request_id: str, body: AssignmentAcceptBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, _action("accept", request_id), body.model_dump(mode="json"))
    result = await requests_api.accept_assignment(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/decline", response_model=RequestProviderView)
async def decline(
    actor: OrgActor, request_id: str, body: AssignmentDeclineBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, _action("decline", request_id), body.model_dump(mode="json"))
    result = await requests_api.decline_assignment(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/withdraw", response_model=RequestProviderView)
async def withdraw(
    actor: OrgActor, request_id: str, body: AssignmentWithdrawBody, idem_key: IdemKey
) -> dict[str, Any]:
    """D2: отказ исполнителя после принятия назначения."""
    idem = make_idempotency(idem_key, _action("withdraw", request_id), body.model_dump(mode="json"))
    result = await requests_api.withdraw_assignment(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        reason=body.reason,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post(
    "/{request_id}/actions/propose-visit", response_model=RequestProviderView, status_code=201
)
async def propose_visit(
    actor: OrgActor, request_id: str, body: AssignmentProposeVisitBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("propose-visit", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.propose_visit(
        actor,
        _rid(request_id),
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
        idem=idem,
    )
    return result.body


@router.post(
    "/{request_id}/actions/create-repair-quote", response_model=RequestProviderView, status_code=201
)
async def create_repair_quote(
    actor: OrgActor, request_id: str, body: AssignmentRepairQuoteBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("create-repair-quote", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.create_repair_quote(
        actor,
        _rid(request_id),
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
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/start-work", response_model=RequestProviderView)
async def start_work(
    actor: OrgActor, request_id: str, body: AssignmentStartWorkBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("start-work", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.start_work(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/mark-en-route", response_model=RequestProviderView)
async def mark_en_route(
    actor: OrgActor, request_id: str, body: AssignmentMarkEnRouteBody, idem_key: IdemKey
) -> dict[str, Any]:
    """Мастер выехал: статус заявки не меняется, в назначении появляется `en_route_at`."""
    idem = make_idempotency(
        idem_key, _action("mark-en-route", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.mark_en_route(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/report-completion", response_model=RequestProviderView)
async def report_completion(
    actor: OrgActor, request_id: str, body: AssignmentReportCompletionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("report-completion", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.report_completion(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        outcome=body.outcome,
        summary=body.summary,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/respond-cancellation", response_model=RequestProviderView)
async def respond_cancellation(
    actor: OrgActor, request_id: str, body: AssignmentCancellationResponseBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("respond-cancellation", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.respond_cancellation(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        cancellation_id=ids.decode("cancellation", body.cancellation_id),
        decision=body.decision,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/warranty-decision", response_model=RequestProviderView)
async def warranty_decision(
    actor: OrgActor, request_id: str, body: AssignmentWarrantyDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("warranty-decision", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.set_warranty_decision(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        decision=body.decision,
        comment=body.comment,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.post("/{request_id}/actions/field-worker", response_model=RequestProviderView)
async def field_worker(
    actor: OrgActor, request_id: str, body: AssignmentFieldWorkerBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, _action("field-worker", request_id), body.model_dump(mode="json")
    )
    result = await requests_api.set_field_worker(
        actor,
        _rid(request_id),
        assignment_id=ids.decode("assignment", body.assignment_id),
        membership_id=ids.decode("membership", body.membership_id) if body.membership_id else None,
        display_name=body.display_name,
        contact_phone=body.contact_phone,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body
