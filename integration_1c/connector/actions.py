from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from connector.contract import (
    AcceptRequest,
    CancellationResponseRequest,
    CompleteRequest,
    DeclineRequest,
    MessageCreateRequest,
    RepairQuoteCreateRequest,
    RepairQuoteItemBody,
    StartWorkRequest,
    VisitProposalCreateRequest,
    WithdrawAssignmentRequest,
)
from connector.onec_directory import (
    Directory,
    amount_to_minor,
    default_window_end,
    parse_onec_datetime,
)
from connector.profile import Profile, Stage

_ACCEPTING_STAGES: frozenset[Stage] = frozenset({"accepted", "in_progress", "done", "not_resolved"})
_WORK_STATUSES = frozenset({"accepted", "scheduled", "in_progress"})
_OPEN_PROPOSAL_STATES = frozenset({"pending", "approved"})
_CLOSED_PROPOSAL_STATES = frozenset({"rejected", "expired", "superseded"})
_CANCELLATION_STAGES: frozenset[Stage] = frozenset({"cancelled", "cancellation_declined"})


@dataclass(frozen=True)
class EstimateLine:
    title: str
    amount_minor: int


@dataclass(frozen=True)
class DocView:
    ref_key: str
    number: str
    data_version: str
    posted: bool
    deletion_mark: bool
    state_name: str | None
    stage: Stage | None
    visit_start: datetime | None = None
    visit_end: datetime | None = None
    visit_amount_minor: int | None = None
    visit_items: tuple[str, ...] = ()
    estimate: tuple[EstimateLine, ...] = ()
    message: str | None = None
    decline_reason: str | None = None
    completion_summary: str | None = None
    cancellation_comment: str | None = None


_SERVICE_FIELDS = ("ref_key", "number", "data_version", "posted", "deletion_mark")


def content_fingerprint(view: DocView) -> str:
    data = asdict(view)
    for name in _SERVICE_FIELDS:
        data.pop(name)
    return fingerprint(data)


@dataclass(frozen=True)
class PlannedAction:
    kind: str
    path: str
    fingerprint: str
    body: dict[str, Any]
    changes_version: bool = True


def fingerprint(*parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


async def extract_view(directory: Directory, doc: dict[str, Any]) -> DocView:
    profile = directory.profile
    state_name = await directory.state_name(doc)
    visit_start = visit_end = None
    visit_amount: int | None = None
    visit_items: list[str] = []
    estimate: list[EstimateLine] = []

    visit_item_keys: set[str] = set()
    if profile.visit is not None:
        for name in profile.visit.amount.table_items:
            key = await directory.item_key(name)
            if key is not None:
                visit_item_keys.add(key)

    if profile.works is not None:
        works = profile.works
        visit_sum: int | None = None
        for row in doc.get(works.table) or []:
            amount = amount_to_minor(row.get(works.amount_field)) or 0
            item_key = str(row.get(works.item_field, "")) if works.item_field else ""
            title = next(
                (str(row[f]).strip() for f in works.title_fields if str(row.get(f) or "").strip()),
                "",
            )
            if not title and item_key:
                title = await directory.item_title(item_key)
            if item_key and item_key in visit_item_keys:
                visit_sum = (visit_sum or 0) + amount
                visit_items.append(title or "Выезд")
                continue
            if title:
                estimate.append(EstimateLine(title=title[:200], amount_minor=max(amount, 0)))
        if profile.visit is not None and profile.visit.amount.table_items:
            visit_amount = visit_sum

    if profile.visit is not None:
        visit_start = parse_onec_datetime(doc.get(profile.visit.start), profile)
        if profile.visit.end:
            visit_end = parse_onec_datetime(doc.get(profile.visit.end), profile)
        if profile.visit.amount.attribute:
            visit_amount = amount_to_minor(doc.get(profile.visit.amount.attribute))

    return DocView(
        ref_key=str(doc["Ref_Key"]),
        number=str(doc.get(profile.document.number_field) or "").strip(),
        data_version=str(doc.get("DataVersion") or ""),
        posted=bool(doc.get("Posted", False)),
        deletion_mark=bool(doc.get("DeletionMark", False)),
        state_name=state_name,
        stage=profile.state.stage_for(state_name),
        visit_start=visit_start,
        visit_end=visit_end,
        visit_amount_minor=visit_amount,
        visit_items=tuple(visit_items),
        estimate=tuple(estimate),
        message=await directory.read(doc, profile.messages.outbound),
        decline_reason=await directory.read(doc, profile.decline_reason.source),
        completion_summary=await directory.read(doc, profile.completion_summary.source),
        cancellation_comment=await directory.read(doc, profile.cancellation.decline_reason.source),
    )


HandledCheck = Callable[[str, str], bool]
ChangedSince = Callable[[str], bool]


def _latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(items, key=lambda i: int(i.get("version") or 0), default=None)


def waiting_topics(card: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    status = card.get("status")
    cancellation = card.get("cancellation") or {}
    if (
        status == "cancellation_pending"
        and cancellation.get("status") == "pending"
        and cancellation.get("id")
    ):
        topics.append(f"cancellation:{cancellation['id']}")
    reported_at = (card.get("completion_report") or {}).get("reported_at")
    if status == "in_progress" and reported_at:
        topics.append(f"completion:{reported_at}")
    latest = _latest(card.get("visit_proposals") or [])
    if latest is not None and latest.get("status") in _CLOSED_PROPOSAL_STATES and latest.get("id"):
        topics.append(f"visit:{latest['id']}")
    return topics


def plan_actions(
    profile: Profile,
    view: DocView,
    card: dict[str, Any],
    handled: HandledCheck,
    changed_since: ChangedSince | None = None,
) -> list[PlannedAction]:
    assignment = card.get("assignment") or {}
    assignment_id = assignment.get("id")
    assignment_state = assignment.get("state")
    status = card.get("status")
    version = card.get("version")
    if not assignment_id or not isinstance(version, int) or "status" not in card:
        return []
    armed = {
        topic: changed_since(topic) if changed_since is not None else True
        for topic in waiting_topics(card)
    }
    if view.deletion_mark:
        return []
    if profile.document.react_only_posted and not view.posted:
        return []

    planned: list[PlannedAction] = []
    stage = view.stage

    def add(kind: str, path: str, fp: str, body: dict[str, Any], **extra: Any) -> None:
        if not handled(kind, fp):
            planned.append(PlannedAction(kind=kind, path=path, fingerprint=fp, body=body, **extra))

    if assignment_state == "pending":
        if stage in _ACCEPTING_STAGES:
            body = AcceptRequest(assignment_id=assignment_id, expected_version=version)
            add("accept", "accept", fingerprint(assignment_id), _dump(body))
        elif stage == "declined":
            reason = view.decline_reason or profile.decline_reason.default
            decline = DeclineRequest(
                assignment_id=assignment_id, reason=reason[:2000], expected_version=version
            )
            add("decline", "decline", fingerprint(assignment_id), _dump(decline))
    elif assignment_state == "accepted":
        if status == "cancellation_pending":
            response = _plan_cancellation(profile, view, card, assignment_id, version, armed)
            if response is not None:
                add("cancellation-response", "cancellation-response", response[0], response[1])
        elif stage == "declined" and status in {"accepted", "scheduled"}:
            reason = view.decline_reason or profile.decline_reason.default
            withdraw = WithdrawAssignmentRequest(
                assignment_id=assignment_id, reason=reason[:2000], expected_version=version
            )
            add("withdraw", "withdraw", fingerprint(assignment_id), _dump(withdraw))
        elif stage in _ACCEPTING_STAGES and status in _WORK_STATUSES:
            visit = _plan_visit(profile, view, card, assignment_id, version, armed)
            if visit is not None:
                add("visit-proposal", "visit-proposals", visit[0], visit[1])
            if stage in {"in_progress", "done", "not_resolved"} and status == "scheduled":
                start = StartWorkRequest(assignment_id=assignment_id, expected_version=version)
                add("start-work", "start-work", fingerprint(assignment_id), _dump(start))
            quote = _plan_quote(profile, view, card, assignment_id, version)
            if quote is not None:
                add("repair-quote", "repair-quotes", quote[0], quote[1])
            reported_at = (card.get("completion_report") or {}).get("reported_at")
            rework_pending = bool(reported_at) and not armed.get(f"completion:{reported_at}", True)
            if stage in {"done", "not_resolved"} and status == "in_progress" and not rework_pending:
                outcome = "resolved" if stage == "done" else "not_resolved"
                summary = view.completion_summary or profile.completion_summary.default
                complete = CompleteRequest(
                    assignment_id=assignment_id,
                    outcome=outcome,
                    summary=summary[:4000],
                    expected_version=version,
                )
                fp = (
                    fingerprint(assignment_id, outcome, str(reported_at))
                    if reported_at
                    else fingerprint(assignment_id, outcome)
                )
                add("complete", "complete", fp, _dump(complete))

    if view.message and assignment_state in {"pending", "accepted"}:
        message = MessageCreateRequest(body=view.message[:4000], assignment_id=assignment_id)
        add(
            "message",
            "messages",
            fingerprint(assignment_id, view.message),
            _dump(message),
            changes_version=False,
        )
    return planned


def _plan_cancellation(
    profile: Profile,
    view: DocView,
    card: dict[str, Any],
    assignment_id: str,
    version: int,
    armed: dict[str, bool],
) -> tuple[str, dict[str, Any]] | None:
    cancellation = card.get("cancellation") or {}
    cancellation_id = cancellation.get("id")
    if cancellation.get("status") != "pending" or not cancellation_id:
        return None
    if view.stage not in _CANCELLATION_STAGES:
        return None
    if not armed.get(f"cancellation:{cancellation_id}", True):
        return None
    accept = view.stage == "cancelled"
    comment = None
    if not accept:
        comment = (view.cancellation_comment or profile.cancellation.decline_reason.default)[:2000]
    decision = "accept" if accept else "decline"
    body = CancellationResponseRequest(
        assignment_id=assignment_id,
        cancellation_id=str(cancellation_id),
        decision=decision,
        comment=comment,
        expected_version=version,
    )
    return fingerprint(assignment_id, str(cancellation_id), decision), _dump(body)


def _plan_visit(
    profile: Profile,
    view: DocView,
    card: dict[str, Any],
    assignment_id: str,
    version: int,
    armed: dict[str, bool],
) -> tuple[str, dict[str, Any]] | None:
    visit = profile.visit
    if visit is None or view.visit_start is None:
        return None
    if view.visit_amount_minor is None and not visit.allow_unknown_price:
        return None
    start = view.visit_start
    end = view.visit_end if view.visit_end and view.visit_end > start else None
    end = end or default_window_end(start, profile)
    amount = view.visit_amount_minor
    proposals = card.get("visit_proposals") or []
    same = [
        p
        for p in proposals
        if _same_moment(p.get("visit_window_start"), start)
        and _same_moment(p.get("visit_window_end"), end)
        and (p.get("price") or {}).get("amount_minor") == amount
    ]
    if any(p.get("status") in _OPEN_PROPOSAL_STATES for p in same):
        return None
    closed = _latest([p for p in same if p.get("status") in _CLOSED_PROPOSAL_STATES])
    latest = _latest(proposals)
    if closed is not None and latest is closed and not armed.get(f"visit:{closed.get('id')}", True):
        return None
    scope = visit.scope_template.format(visit_items=", ".join(view.visit_items) or "Выезд")
    body = VisitProposalCreateRequest(
        assignment_id=assignment_id,
        visit_window_start=start,
        visit_window_end=end,
        amount_minor=amount,
        currency="RUB",
        zero_cost_reason="Бесплатный выезд" if amount == 0 else None,
        scope_description=scope.strip() or None,
        expected_version=version,
    )
    fp = fingerprint(assignment_id, start.isoformat(), end.isoformat(), amount)
    if closed is not None:
        fp = fingerprint(
            assignment_id, start.isoformat(), end.isoformat(), amount, closed.get("id")
        )
    return fp, _dump(body)


def _plan_quote(
    profile: Profile, view: DocView, card: dict[str, Any], assignment_id: str, version: int
) -> tuple[str, dict[str, Any]] | None:
    estimate = profile.estimate
    if estimate is None or not view.estimate or view.stage not in estimate.stages:
        return None
    lines = view.estimate[:50]
    items = [(line.title, line.amount_minor) for line in lines]
    for quote in card.get("repair_quotes") or []:
        if quote.get("status") not in _OPEN_PROPOSAL_STATES:
            continue
        existing = [(i.get("title"), i.get("amount_minor")) for i in quote.get("items") or []]
        if existing == items:
            return None
    total = sum(amount for _, amount in items)
    description = estimate.description_template.format(
        number=view.number, items="; ".join(title for title, _ in items)
    )
    body = RepairQuoteCreateRequest(
        assignment_id=assignment_id,
        description_of_work=description[:4000],
        items=[RepairQuoteItemBody(title=t, amount_minor=a) for t, a in items],
        amount_minor=total,
        currency="RUB",
        zero_cost_reason="Работы без оплаты" if total == 0 else None,
        expected_version=version,
    )
    return fingerprint(assignment_id, items), _dump(body)


def _same_moment(value: Any, moment: datetime) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed == moment


def _dump(model: Any) -> dict[str, Any]:
    return dict(model.model_dump(mode="json", exclude_none=True))
