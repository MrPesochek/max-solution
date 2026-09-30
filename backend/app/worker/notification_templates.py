import dataclasses
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import actions as bot_actions
from app.adapters.bot import conditions, keyboards, texts
from app.core import ids
from app.db.enums import (
    AssignmentState,
    CancellationStatus,
    RepairQuoteStatus,
    RequestStatus,
    VisitProposalStatus,
)
from app.db.models import (
    Assignment,
    CancellationRequest,
    Location,
    Membership,
    Organization,
    RepairQuote,
    RepairRequest,
    RequestEvent,
    User,
    VisitProposal,
)
from app.infra.config import get_settings
from app.infra.max.types import (
    OPEN_APP_PAYLOAD_PREFIX,
    Button,
    ButtonCallback,
    OutgoingAttachment,
    TextFormat,
    keyboard,
    open_webapp_button,
)

FALLBACK_TEXT = "Есть обновление"
NOW_OUTDATED = "Условия уже неактуальны — откройте заявку в приложении."


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    text: str
    format: TextFormat | None = None
    attachments: list[OutgoingAttachment] | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: uuid.UUID
    membership_id: uuid.UUID | None = None


Renderer = Callable[[dict[str, Any]], OutgoingMessage]
_REGISTRY: dict[str, Renderer] = {}

StatefulRenderer = Callable[
    [AsyncSession, dict[str, Any], Recipient, datetime], Awaitable[OutgoingMessage]
]
_STATEFUL: dict[str, StatefulRenderer] = {}


def template(notification_type: str) -> Callable[[Renderer], Renderer]:
    def decorator(fn: Renderer) -> Renderer:
        _REGISTRY[notification_type] = fn
        return fn

    return decorator


def stateful_template(notification_type: str) -> Callable[[StatefulRenderer], StatefulRenderer]:
    def decorator(fn: StatefulRenderer) -> StatefulRenderer:
        _STATEFUL[notification_type] = fn
        return fn

    return decorator


def _public_id(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _request_message(text: str, payload: dict[str, Any]) -> OutgoingMessage:
    return OutgoingMessage(
        text=text, attachments=[open_webapp_button("request", _public_id(payload, "request_id"))]
    )


async def _action_button(
    session: AsyncSession,
    recipient: Recipient,
    action_type: str,
    now: datetime,
    *,
    label: str,
    object_type: str,
    object_id: uuid.UUID,
    expected_version: int | None = None,
    proposal_version: int | None = None,
    params: dict[str, Any] | None = None,
) -> Button:
    code = await bot_actions.make_action(
        session,
        recipient.user_id,
        action_type,
        now,
        object_type=object_type,
        object_id=object_id,
        expected_version=expected_version,
        proposal_version=proposal_version,
        params=params,
        membership_id=recipient.membership_id,
    )
    return keyboards.action_button(label, code)


@template("request.assigned")
def _request_assigned(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Новая заявка на ремонт: нужен ответ исполнителя", payload)


@template("request.submitted")
def _request_submitted(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заявка отправлена исполнителю", payload)


@template("request.accepted")
def _request_accepted(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель принял заявку", payload)


@template("request.approval_required")
def _approval_required(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Сотрудник отправил заявку на согласование", payload)


@template("assignment.revoked")
def _assignment_revoked(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Назначение по заявке отозвано заказчиком", payload)


@template("request.cancelled")
def _request_cancelled(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заявка отменена заказчиком", payload)


@template("cancellation.withdrawn")
def _cancellation_withdrawn(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заказчик отозвал запрос на отмену", payload)


@template("cancellation.forced")
def _cancellation_forced(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заявка прекращена заказчиком в одностороннем порядке", payload)


@template("request.closed")
def _request_closed(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заявка закрыта", payload)


@template("request.auto_closed")
def _request_auto_closed(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message(
        "Заявка закрыта автоматически: результат работ не подтверждён в срок", payload
    )


@template("completion.rejected")
def _completion_rejected(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Заказчик отметил: проблема осталась", payload)


@template("request.declined")
def _request_declined(payload: dict[str, Any]) -> OutgoingMessage:
    reason = payload.get("reason")
    text = "Исполнитель отклонил заявку" + (f": {reason}" if reason else "")
    return _request_message(text, payload)


@template("assignment.withdrawn")
def _assignment_withdrawn(payload: dict[str, Any]) -> OutgoingMessage:
    reason = payload.get("reason")
    text = "Исполнитель отказался от заявки" + (f": {reason}" if reason else "")
    return _request_message(text, payload)


@template("offer.submitted")
def _offer_submitted(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Новое предложение исполнителя — смотрите в «Мои заявки»", payload)


@template("offer.withdrawn")
def _offer_withdrawn(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель отозвал предложение", payload)


@template("search.no_providers")
def _search_no_providers(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Подходящих исполнителей не нашлось", payload)


@template("search.expired")
def _search_expired(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Поиск исполнителя завершён без результата", payload)


@template("marketplace.request.available")
def _marketplace_available(payload: dict[str, Any]) -> OutgoingMessage:
    return OutgoingMessage(
        text="Доступна новая заявка на бирже — смотрите «Доступные заявки»",
        attachments=[open_webapp_button("available", _public_id(payload, "request_id"))],
    )


@template("marketplace.request.closed")
def _marketplace_closed(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Подбор исполнителя по заявке завершён", payload)


@template("offer.expired")
def _offer_expired(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Срок вашего предложения истёк", payload)


@template("offer.selected")
def _offer_selected(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message(
        "Ваше предложение выбрано — подтвердите готовность во «Входящих»", payload
    )


@template("assignment.confirmed")
def _assignment_confirmed(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Вы подтвердили и приняли заявку", payload)


@template("assignment.declined")
def _assignment_declined(payload: dict[str, Any]) -> OutgoingMessage:
    reason = payload.get("reason")
    text = "Исполнитель отказался от выбранного назначения" + (f": {reason}" if reason else "")
    return _request_message(text, payload)


@template("assignment.expired")
def _assignment_expired(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Срок подтверждения назначения истёк", payload)


@template("field_worker.assigned")
def _field_worker_assigned(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Назначен выездной сотрудник", payload)


@template("warranty_decision.stated")
def _warranty_stated(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель сообщил решение о гарантии", payload)


@template("work.started")
def _work_started(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель начал работу", payload)


@template("cancellation.accepted")
def _cancellation_accepted(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель принял отмену заявки", payload)


@template("cancellation.disputed")
def _cancellation_disputed(payload: dict[str, Any]) -> OutgoingMessage:
    return _request_message("Исполнитель не согласен с отменой — нужно решение", payload)


@template("integration.api_key.created")
def _api_key_created(payload: dict[str, Any]) -> OutgoingMessage:
    name = _public_id(payload, "name")
    suffix = f" «{name}»" if name else ""
    return OutgoingMessage(
        text=f"Выпущен ключ интеграции{suffix}", attachments=[open_webapp_button("integration")]
    )


@template("verification.reopened")
def _verification_reopened(payload: dict[str, Any]) -> OutgoingMessage:
    return OutgoingMessage(
        text="Оператор открыл повторную проверку: обновите сведения в профиле",
        attachments=[open_webapp_button("profile")],
    )


@template("integration.webhook.changed")
def _webhook_changed(payload: dict[str, Any]) -> OutgoingMessage:
    return OutgoingMessage(
        text="Изменены настройки вебхуков интеграции",
        attachments=[open_webapp_button("integration")],
    )


@stateful_template("visit_proposal.created")
async def _visit_proposal_created(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    proposal_public_id = _public_id(payload, "visit_proposal_id")
    proposal_version = payload.get("proposal_version")
    if request_public_id is None or proposal_public_id is None:
        return _request_message("Исполнитель предложил условия выезда", payload)

    request_id = ids.decode("request", request_public_id)
    proposal_id = ids.decode("visit_proposal", proposal_public_id)
    request = await session.get(RepairRequest, request_id)
    proposal = await session.get(VisitProposal, proposal_id)
    number = request.request_number if request is not None else "—"
    if proposal is None or request is None:
        return _request_message("Исполнитель предложил условия выезда", payload)

    lines = conditions.visit_lines(
        number=number,
        version=proposal.version,
        window_start=proposal.visit_window_start,
        window_end=proposal.visit_window_end,
        amount_minor=proposal.visit_amount_minor,
        currency=proposal.currency,
        zero_cost_reason=proposal.zero_cost_reason,
        vat_mode=proposal.vat_mode,
        scope=proposal.scope_description,
        valid_until=proposal.valid_until,
        tz=request.location_snapshot.get("timezone"),
    )
    current = (
        proposal.status == VisitProposalStatus.PENDING
        and proposal_version is not None
        and proposal.version == proposal_version
    )
    if not current:
        lines.append(NOW_OUTDATED)
        return OutgoingMessage(
            text="\n".join(lines), attachments=[open_webapp_button("request", request_public_id)]
        )

    approve = await _action_button(
        session,
        recipient,
        "visit_proposal.approve",
        now,
        label=texts.BUTTON_APPROVE_VISIT.format(version=proposal.version),
        object_type="visit_proposal",
        object_id=proposal.id,
        expected_version=request.version,
        proposal_version=proposal.version,
        params={"request_id": request_public_id},
    )
    reject = await _action_button(
        session,
        recipient,
        "visit_proposal.reject",
        now,
        label=texts.BUTTON_REJECT_VISIT,
        object_type="visit_proposal",
        object_id=proposal.id,
        expected_version=request.version,
        proposal_version=proposal.version,
        params={"request_id": request_public_id},
    )
    return OutgoingMessage(text="\n".join(lines), attachments=[keyboards.rows([approve, reject])])


@stateful_template("repair_quote.created")
async def _repair_quote_created(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    quote_public_id = _public_id(payload, "repair_quote_id")
    quote_version = payload.get("quote_version")
    if request_public_id is None or quote_public_id is None:
        return _request_message("Исполнитель прислал смету ремонта", payload)

    request_id = ids.decode("request", request_public_id)
    quote_id = ids.decode("repair_quote", quote_public_id)
    request = await session.get(RepairRequest, request_id)
    quote = await session.get(RepairQuote, quote_id)
    if request is None or quote is None:
        return _request_message("Исполнитель прислал смету ремонта", payload)

    lines = conditions.quote_lines(
        number=request.request_number,
        version=quote.version,
        description=quote.description_of_work,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        zero_cost_reason=quote.zero_cost_reason,
        vat_mode=quote.vat_mode,
        valid_until=quote.valid_until,
        tz=request.location_snapshot.get("timezone"),
    )
    current = (
        quote.status == RepairQuoteStatus.PENDING
        and quote_version is not None
        and quote.version == quote_version
    )
    if not current:
        lines.append(NOW_OUTDATED)
        return OutgoingMessage(
            text="\n".join(lines), attachments=[open_webapp_button("request", request_public_id)]
        )

    approve = await _action_button(
        session,
        recipient,
        "repair_quote.approve",
        now,
        label=texts.BUTTON_APPROVE_QUOTE.format(version=quote.version),
        object_type="repair_quote",
        object_id=quote.id,
        expected_version=request.version,
        proposal_version=quote.version,
        params={"request_id": request_public_id},
    )
    reject = await _action_button(
        session,
        recipient,
        "repair_quote.reject",
        now,
        label=texts.BUTTON_REJECT_QUOTE,
        object_type="repair_quote",
        object_id=quote.id,
        expected_version=request.version,
        proposal_version=quote.version,
        params={"request_id": request_public_id},
    )
    return OutgoingMessage(text="\n".join(lines), attachments=[keyboards.rows([approve, reject])])


@stateful_template("completion.reported")
async def _completion_reported(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    outcome = payload.get("outcome")
    text_outcome = "проблема решена" if outcome == "resolved" else "проблема не решена"
    base_text = f"Исполнитель сообщил о завершении работ: {text_outcome}."
    if request_public_id is None:
        return OutgoingMessage(text=base_text, attachments=[open_webapp_button("home")])

    request = await session.get(RepairRequest, ids.decode("request", request_public_id))
    if request is None or request.status != "completion_reported":
        return OutgoingMessage(
            text=f"{base_text} {NOW_OUTDATED}",
            attachments=[open_webapp_button("request", request_public_id)],
        )
    confirm = await _action_button(
        session,
        recipient,
        "completion.confirm",
        now,
        label="Подтвердить",
        object_type="request",
        object_id=request.id,
        expected_version=request.version,
    )
    problem = await _action_button(
        session,
        recipient,
        "completion.problem",
        now,
        label="Проблема осталась",
        object_type="request",
        object_id=request.id,
        expected_version=request.version,
    )
    return OutgoingMessage(text=base_text, attachments=[keyboards.rows([confirm, problem])])


@stateful_template("completion.reminder")
async def _completion_reminder(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    message = await _completion_reported(session, payload, recipient, now)
    return OutgoingMessage(
        text=f"Напоминание: результат работ ждёт подтверждения. {message.text}",
        attachments=message.attachments,
    )


@stateful_template("request.assigned")
async def _request_assigned_stateful(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    assignment_public_id = _public_id(payload, "assignment_id")
    base_text = "Новая заявка на ремонт: нужен ответ исполнителя"
    if request_public_id is None or assignment_public_id is None:
        return _request_message(base_text, payload)
    request = await session.get(RepairRequest, ids.decode("request", request_public_id))
    assignment = await session.get(Assignment, ids.decode("assignment", assignment_public_id))
    if request is None or assignment is None or assignment.state != AssignmentState.PENDING:
        return OutgoingMessage(
            text=f"{base_text}. {NOW_OUTDATED}",
            attachments=[open_webapp_button("request", request_public_id)],
        )
    accept = await _action_button(
        session,
        recipient,
        "assignment.accept",
        now,
        label="Принять",
        object_type="assignment",
        object_id=assignment.id,
        expected_version=request.version,
        params={"request_id": request_public_id},
    )
    decline = await _action_button(
        session,
        recipient,
        "assignment.decline_start",
        now,
        label="Отклонить",
        object_type="assignment",
        object_id=assignment.id,
        expected_version=request.version,
        params={"request_id": request_public_id},
    )
    return OutgoingMessage(text=base_text, attachments=[keyboards.rows([accept, decline])])


@stateful_template("cancellation.requested")
async def _cancellation_requested(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    base_text = "Заказчик запросил отмену заявки"
    if request_public_id is None:
        return _request_message(base_text, payload)
    request_id = ids.decode("request", request_public_id)
    request = await session.get(RepairRequest, request_id)
    cancellation = await _own_cancellation(session, request_id, payload)
    if request is None or cancellation is None or cancellation.status != CancellationStatus.PENDING:
        return OutgoingMessage(
            text=f"{base_text}. {NOW_OUTDATED}",
            attachments=[open_webapp_button("request", request_public_id)],
        )
    assignment_public_id = _public_id(payload, "assignment_id") or ""
    params = {"request_id": request_public_id, "assignment_id": assignment_public_id}
    accept = await _action_button(
        session,
        recipient,
        "cancellation.provider_accept",
        now,
        label="Принять",
        object_type="cancellation",
        object_id=cancellation.id,
        expected_version=request.version,
        params=params,
    )
    decline = await _action_button(
        session,
        recipient,
        "cancellation.provider_decline",
        now,
        label="Не согласен",
        object_type="cancellation",
        object_id=cancellation.id,
        expected_version=request.version,
        params=params,
    )
    text = f"{base_text}: {cancellation.reason or '—'}"
    return OutgoingMessage(text=text, attachments=[keyboards.rows([accept, decline])])


@stateful_template("cancellation.reminder")
async def _cancellation_reminder(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    message = await _cancellation_requested(session, payload, recipient, now)
    request = await _request_from(session, payload)
    text = f"Напоминание: заказчик ждёт ответа на запрос отмены. {message.text}"
    if request is not None:
        text = f"{request_header(request)}\n{text}"
    return dataclasses.replace(message, text=text)


@stateful_template("cancellation.no_response")
async def _cancellation_no_response(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    base = _request_message(
        "Исполнитель не ответил на запрос отмены в срок. "
        "Можно прекратить работы самостоятельно — в карточке заявки.",
        payload,
    )
    request = await _request_from(session, payload)
    cancellation_public_id = _public_id(payload, "cancellation_id")
    cancellation = (
        await session.get(CancellationRequest, ids.decode("cancellation", cancellation_public_id))
        if cancellation_public_id is not None
        else None
    )
    if request is None or cancellation is None:
        return base
    if cancellation.status != CancellationStatus.PENDING:
        return dataclasses.replace(base, skip_reason="cancellation_answered")
    return _with_header(request, base)


async def _own_cancellation(
    session: AsyncSession, request_id: uuid.UUID, payload: dict[str, Any]
) -> CancellationRequest | None:
    cancellation_public_id = _public_id(payload, "cancellation_id")
    assignment_public_id = _public_id(payload, "assignment_id")
    if assignment_public_id is None:
        return None
    stmt = select(CancellationRequest).where(
        CancellationRequest.request_id == request_id,
        CancellationRequest.assignment_id == ids.decode("assignment", assignment_public_id),
    )
    if cancellation_public_id is not None:
        stmt = stmt.where(
            CancellationRequest.id == ids.decode("cancellation", cancellation_public_id)
        )
    else:
        stmt = stmt.order_by(CancellationRequest.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


@stateful_template("message.created")
async def _message_created(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request_public_id = _public_id(payload, "request_id")
    if request_public_id is None:
        return OutgoingMessage(
            text="Новое сообщение по заявке", attachments=[open_webapp_button("home")]
        )
    params: dict[str, Any] = {}
    if _public_id(payload, "assignment_id"):
        params["assignment_id"] = _public_id(payload, "assignment_id")
    if _public_id(payload, "thread_provider_org_id"):
        params["thread_provider_org_id"] = _public_id(payload, "thread_provider_org_id")
    reply = await _action_button(
        session,
        recipient,
        "message.reply_start",
        now,
        label="Ответить",
        object_type="request",
        object_id=ids.decode("request", request_public_id),
        params=params,
    )
    open_button = keyboards.open_app("Открыть", "request", request_public_id)
    return OutgoingMessage(
        text="Новое сообщение по заявке",
        attachments=[keyboards.rows([reply], [open_button])],
    )


def request_header(request: RepairRequest) -> str:
    category = (request.equipment_snapshot or {}).get("category_name")
    return f"№{request.request_number}" + (f" · {category}" if category else "")


async def _request_from(session: AsyncSession, payload: dict[str, Any]) -> RepairRequest | None:
    request_public_id = _public_id(payload, "request_id")
    if request_public_id is None:
        return None
    try:
        request_id = ids.decode("request", request_public_id)
    except ValueError:
        return None
    return await session.get(RepairRequest, request_id)


def _with_header(request: RepairRequest, message: OutgoingMessage) -> OutgoingMessage:
    return dataclasses.replace(message, text=f"{request_header(request)}\n{message.text}")


@stateful_template("field_worker.en_route")
async def _field_worker_en_route(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    base = _request_message("Мастер выехал к вам", payload)
    request = await _request_from(session, payload)
    if request is None:
        return dataclasses.replace(base, skip_reason="request_missing")
    assignment = (
        await session.execute(
            select(Assignment).where(
                Assignment.request_id == request.id,
                Assignment.state == AssignmentState.ACCEPTED,
            )
        )
    ).scalar_one_or_none()
    marked = assignment.en_route_at if assignment is not None else None
    stamp = payload.get("en_route_at")
    if (
        marked is None
        or request.status != RequestStatus.SCHEDULED
        or (isinstance(stamp, str) and datetime.fromisoformat(stamp) != marked)
    ):
        return dataclasses.replace(base, skip_reason="en_route_outdated")
    return _with_header(request, base)


@stateful_template("request.returned_to_draft")
async def _returned_to_draft(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request = await _request_from(session, payload)
    if request is None:
        return _request_message("Заявку вернули на доработку", payload)
    comment = (
        await session.execute(
            select(RequestEvent.payload)
            .where(
                RequestEvent.request_id == request.id,
                RequestEvent.event_type == "RequestReturnedToDraft",
            )
            .order_by(RequestEvent.occurred_at.desc(), RequestEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    text = "Руководитель вернул заявку на доработку"
    note = comment.get("comment") if isinstance(comment, dict) else None
    if isinstance(note, str) and note:
        text += f": {note}"
    return _with_header(request, _request_message(text, payload))


@stateful_template("own_service.no_answer")
async def _own_service_no_answer(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    request = await _request_from(session, payload)
    base_text = "Ваш сервис долго не отвечает на заявку"
    if request is None:
        return _request_message(base_text, payload)
    request_public_id = ids.encode("request", request.id)
    assignment = (
        await session.execute(
            select(Assignment).where(
                Assignment.request_id == request.id,
                Assignment.state == AssignmentState.PENDING,
            )
        )
    ).scalar_one_or_none()
    if request.status != RequestStatus.AWAITING_PROVIDER or assignment is None:
        return dataclasses.replace(
            _request_message(base_text, payload), skip_reason="own_service_answered"
        )
    lines = [request_header(request), base_text + "."]
    provider = await session.get(Organization, assignment.provider_org_id)
    if provider is not None:
        contact = provider.contact_phone
        lines.append(f"{provider.display_name}" + (f": {contact}" if contact else ""))
    lines.append("Можно позвонить сервису или найти другого исполнителя.")
    return OutgoingMessage(
        text="\n".join(lines),
        attachments=[
            keyboards.rows(
                [keyboards.open_app("Найти другого", "request", request_public_id)],
            )
        ],
    )


@stateful_template("membership.access_requested")
async def _access_requested(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    lines = ["Сотрудник просит открыть ему доступ"]
    membership_public_id = _public_id(payload, "membership_id")
    if membership_public_id is not None:
        membership = await session.get(Membership, ids.decode("membership", membership_public_id))
        user = await session.get(User, membership.user_id) if membership is not None else None
        if user is not None:
            lines[0] = f"{user.display_name} просит открыть доступ"
    location_public_id = _public_id(payload, "location_id")
    if location_public_id is not None:
        location = await session.get(Location, ids.decode("location", location_public_id))
        if location is not None:
            lines.append(f"Точка: {location.name}")
    note = payload.get("note")
    if isinstance(note, str) and note:
        lines.append(f"Комментарий: {note}")
    return OutgoingMessage(
        text="\n".join(lines),
        attachments=[open_webapp_button("organization")],
    )


@stateful_template("membership.pending_approval")
async def _membership_pending_approval(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    name: str | None = None
    membership_public_id = _public_id(payload, "membership_id")
    if membership_public_id is not None:
        membership = await session.get(Membership, ids.decode("membership", membership_public_id))
        if membership is not None and membership.status != "pending":
            return OutgoingMessage(
                text="Заявка на вступление уже рассмотрена",
                attachments=[open_webapp_button("organization")],
                skip_reason="membership_decided",
            )
        user = await session.get(User, membership.user_id) if membership is not None else None
        name = user.display_name if user is not None else None
    head = f"Ждёт подтверждения: {name}" if name else "Новый сотрудник ждёт подтверждения"
    return OutgoingMessage(
        text=f"{head}\nСверьте имя в MAX с тем, кого приглашали, и подтвердите доступ.",
        attachments=[open_webapp_button("organization")],
    )


@stateful_template("invitation.foreign_attempt")
async def _invitation_foreign_attempt(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    lines = ["Именное приглашение попробовали принять с чужого аккаунта MAX"]
    user_public_id = _public_id(payload, "user_id")
    if user_public_id is not None:
        user = await session.get(User, ids.decode("user", user_public_id))
        if user is not None:
            lines.append(f"Аккаунт: {user.display_name}")
    lines.append("Доступ не выдан, приглашение действует. Если ссылку переслали, отзовите его.")
    return OutgoingMessage(text="\n".join(lines), attachments=[open_webapp_button("organization")])


@stateful_template("membership.approved")
async def _membership_approved(
    session: AsyncSession, payload: dict[str, Any], recipient: Recipient, now: datetime
) -> OutgoingMessage:
    text = "Руководитель подтвердил ваш доступ к организации"
    membership_public_id = _public_id(payload, "membership_id")
    if membership_public_id is not None:
        membership = await session.get(Membership, ids.decode("membership", membership_public_id))
        org = (
            await session.get(Organization, membership.organization_id)
            if membership is not None
            else None
        )
        if org is not None:
            text = f"Руководитель «{org.display_name}» подтвердил ваш доступ"
    return OutgoingMessage(text=text, attachments=[open_webapp_button("home")])


async def render(
    session: AsyncSession,
    notification_type: str,
    payload: dict[str, Any],
    *,
    recipient_user_id: uuid.UUID,
    now: datetime,
    recipient_membership_id: uuid.UUID | None = None,
) -> OutgoingMessage:
    recipient = Recipient(recipient_user_id, recipient_membership_id)
    stateful = _STATEFUL.get(notification_type)
    if stateful is not None:
        message = await stateful(session, payload, recipient, now)
    else:
        renderer = _REGISTRY.get(notification_type)
        if renderer is None:
            message = OutgoingMessage(text=FALLBACK_TEXT, attachments=[open_webapp_button("home")])
        else:
            message = renderer(payload)
            request = await _request_from(session, payload)
            if request is not None:
                message = _with_header(request, message)
    return await _bind_open_app_buttons(session, message, recipient, now)


async def _bind_open_app_buttons(
    session: AsyncSession, message: OutgoingMessage, recipient: Recipient, now: datetime
) -> OutgoingMessage:
    settings = get_settings()
    if settings.max_webapp_mode != "link" or not message.attachments:
        return message
    ttl = timedelta(seconds=settings.bot_open_app_action_ttl_seconds)
    attachments: list[OutgoingAttachment] = []
    for attachment in message.attachments:
        buttons = getattr(attachment.payload, "buttons", None)
        if not isinstance(buttons, list):
            attachments.append(attachment)
            continue
        rows: list[list[Button]] = []
        for row in buttons:
            bound: list[Button] = []
            for button in row:
                if isinstance(button, ButtonCallback) and (button.payload or "").startswith(
                    OPEN_APP_PAYLOAD_PREFIX
                ):
                    target = (button.payload or "")[len(OPEN_APP_PAYLOAD_PREFIX) :]
                    code = await bot_actions.make_action(
                        session,
                        recipient.user_id,
                        bot_actions.OPEN_APP_ACTION,
                        now,
                        params={bot_actions.OPEN_APP_TARGET_PARAM: target} if target else None,
                        ttl=ttl,
                        membership_id=recipient.membership_id,
                    )
                    button = keyboards.action_button(button.text, code)
                bound.append(button)
            rows.append(bound)
        attachments.append(keyboard(rows))
    return dataclasses.replace(message, attachments=attachments)


def registered_types() -> frozenset[str]:
    return frozenset(_REGISTRY) | frozenset(_STATEFUL)


__all__ = [
    "FALLBACK_TEXT",
    "OutgoingMessage",
    "Recipient",
    "registered_types",
    "render",
    "request_header",
    "stateful_template",
    "template",
]
