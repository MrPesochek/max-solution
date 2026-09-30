from __future__ import annotations

import hashlib
import hmac
import itertools
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

_SIGNATURE_PREFIX = "sha256="


def sign(secret: str, timestamp: int, raw_body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{mac}"


def _error(code: str, message: str, status: int, **details: Any) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": "r-test", "details": details}},
        status_code=status,
    )


class FakePlatform:
    def __init__(self) -> None:
        self.requests: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.attachments: dict[str, bytes] = {}
        self.subscription: dict[str, Any] | None = None
        self.deleted_subscriptions: list[str] = []
        self.fail_list_subscriptions = False
        self.events: list[dict[str, Any]] = []
        self.idempotency: dict[str, tuple[str, Any, Any, int]] = {}
        self.idempotency_key_log: list[tuple[str, str]] = []
        self.external_references: dict[str, str] = {}
        self.call_counts: dict[str, int] = {}
        self._seq = itertools.count(1)
        self.cursor_expired = False
        self.fail_times: dict[str, int] = {}
        self.lose_response_once: set[str] = set()
        self.conflict_once: set[str] = set()

    def add_request(self, request_id: str, **fields: Any) -> dict[str, Any]:
        card: dict[str, Any] = {
            "id": request_id,
            "request_number": len(self.requests) + 101,
            "status": "awaiting_provider",
            "route": "own_service",
            "urgency": "normal",
            "version": 1,
            "symptom_description": "Не морозит холодильная витрина",
            "error_code": "E1",
            "equipment": {
                "id": "eq_demo",
                "category_id": "cat_demo",
                "category_name": "холодильная витрина",
                "brand": "Полюс",
                "model": "ВХС-1",
                "serial_number": None,
                "notes": None,
            },
            "location": {
                "id": "loc_demo",
                "name": None,
                "city_id": "city_demo",
                "district_id": None,
                "address": None,
                "timezone": "Europe/Moscow",
                "contact_name": None,
                "contact_phone": None,
            },
            "contacts_disclosed": False,
            "photos_incomplete": False,
            "photos_incomplete_reason": None,
            "submitted_at": "2026-09-19T08:00:00Z",
            "created_at": "2026-09-19T08:00:00Z",
            "assignment": {
                "id": f"asg_{request_id}",
                "request_id": request_id,
                "provider_organization_id": "org_provider_demo",
                "route": "own_service",
                "state": "pending",
                "warranty_decision": "not_stated",
                "warranty_decision_comment": None,
                "field_worker": None,
                "decline_reason": None,
                "revoke_reason": None,
                "withdrawal_reason": None,
                "expires_at": None,
                "responded_at": None,
                "created_at": "2026-09-19T08:00:00Z",
            },
            "visit_proposals": [],
            "repair_quotes": [],
            "cancellation": None,
            "attachments": [],
        }
        card.update(fields)
        self.requests[request_id] = card
        self.messages.setdefault(request_id, [])
        return card

    def bump(self, request_id: str, **fields: Any) -> dict[str, Any]:
        card = self.requests[request_id]
        card["version"] += 1
        card.update(fields)
        return card

    def add_attachment(
        self,
        attachment_id: str,
        request_id: str,
        *,
        content: bytes = b"\xff\xd8\xff\xe0fake-jpeg",
        slot: str | None = "overview",
        processing_state: str = "ready",
    ) -> dict[str, Any]:
        meta = {
            "id": attachment_id,
            "owner_kind": "request",
            "request_id": request_id,
            "message_id": None,
            "equipment_id": None,
            "slot": slot,
            "visibility_class": "request_private",
            "processing_state": processing_state,
            "publication_state": None,
            "rejected_reason": None,
            "mime_type": "image/jpeg",
            "byte_size": len(content),
            "pixel_width": None,
            "pixel_height": None,
            "created_at": "2026-09-19T09:00:00Z",
        }
        self.attachments[attachment_id] = content
        self.requests[request_id]["attachments"].append(meta)
        return meta

    def approve_visit(self, request_id: str) -> None:
        card = self.requests[request_id]
        card["visit_proposals"][-1]["status"] = "approved"
        self.bump(request_id, status="scheduled")

    def reject_visit(self, request_id: str) -> None:
        self.requests[request_id]["visit_proposals"][-1]["status"] = "rejected"
        self.bump(request_id)

    def request_cancellation(
        self, request_id: str, *, reason: str = "Сами починили", cancellation_id: str = "can_1"
    ) -> None:
        card = self.requests[request_id]
        card["cancellation"] = {
            "id": cancellation_id,
            "assignment_id": card["assignment"]["id"],
            "target": "cancel_request",
            "previous_status": card["status"],
            "status": "pending",
            "reason": reason,
            "provider_response": None,
            "disputed": False,
            "dispute_deadline_at": None,
            "resolution_kind": None,
            "resolved_at": None,
            "created_at": "2026-09-19T11:00:00Z",
        }
        self.bump(request_id, status="cancellation_pending")

    def reject_completion(self, request_id: str) -> None:
        self.bump(request_id, status="in_progress")

    def count(self, name: str) -> int:
        return self.call_counts.get(name, 0)

    def keys_for(self, operation: str) -> list[str]:
        return [key for op, key in self.idempotency_key_log if op == operation]


def build_app(platform: FakePlatform) -> FastAPI:
    app = FastAPI()

    def _count(name: str) -> None:
        platform.call_counts[name] = platform.call_counts.get(name, 0) + 1

    async def _mutation(
        operation: str,
        request_id: str,
        request: Request,
        key: str | None,
        apply: Any,
        *,
        status_code: int = 200,
        check_version: bool = True,
    ) -> Any:
        _count(operation)
        body = await request.json()
        if key is not None:
            platform.idempotency_key_log.append((operation, key))
            seen = platform.idempotency.get(key)
            if seen is not None:
                scope, prev_body, response, prev_status = seen
                if scope != f"{operation}:{request_id}" or prev_body != body:
                    return _error("IDEMPOTENCY_CONFLICT", "ключ с другим телом", 409)
                _count(f"{operation}:replay")
                return JSONResponse(response, status_code=prev_status)
        if platform.fail_times.get(operation, 0) > 0:
            platform.fail_times[operation] -= 1
            return _error("TEMPORARY", "попробуйте ещё раз", 503)
        card = platform.requests.get(request_id)
        if card is None:
            return _error("NOT_FOUND", "не найдено", 404)
        if operation in platform.conflict_once:
            platform.conflict_once.discard(operation)
            platform.bump(request_id)
        if check_version and body.get("expected_version") != card["version"]:
            return _error(
                "VERSION_CONFLICT", "Заявка изменена", 409, current_version=card["version"]
            )
        result = apply(card, body)
        if isinstance(result, JSONResponse):
            return result
        _count(f"{operation}:applied")
        if key is not None:
            platform.idempotency[key] = (f"{operation}:{request_id}", body, result, status_code)
        if operation in platform.lose_response_once:
            platform.lose_response_once.discard(operation)
            return JSONResponse({"detail": "bad gateway"}, status_code=502)
        return JSONResponse(result, status_code=status_code)

    def _transition(card: dict[str, Any], expected: str, target: str) -> Any:
        if card["status"] != expected:
            return _error("INVALID_TRANSITION", f"недопустимо из {card['status']}", 409)
        platform.bump(card["id"], status=target)
        return dict(card)

    @app.get("/api/v1/requests/{request_id}")
    async def get_request(request_id: str) -> Any:
        _count("get_request")
        card = platform.requests.get(request_id)
        if card is None:
            return _error("NOT_FOUND", "не найдено", 404)
        if card["assignment"].get("state") == "revoked":
            return {"request_id": request_id, "assignment": card["assignment"]}
        return card

    @app.get("/api/v1/requests")
    async def list_requests(cursor: str | None = None) -> Any:
        _count("list_requests")
        items = [
            {
                "id": c["id"],
                "request_number": c["request_number"],
                "status": c["status"],
                "route": c["route"],
                "urgency": c["urgency"],
                "version": c["version"],
                "updated_at": "2026-09-19T09:00:00Z",
                "created_at": c["created_at"],
            }
            for c in platform.requests.values()
        ]
        return {"items": items, "next_cursor": None}

    @app.post("/api/v1/requests/{request_id}/external-reference")
    async def external_reference(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            platform.external_references[request_id] = body["external_id"]
            return dict(platform.bump(request_id))

        return await _mutation("external_reference", request_id, request, key, apply)

    @app.post("/api/v1/requests/{request_id}/accept")
    async def accept(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            if card["assignment"]["state"] != "pending":
                return _error("INVALID_TRANSITION", "назначение не ожидает ответа", 409)
            card["assignment"]["state"] = "accepted"
            card["location"].update(
                {
                    "name": "Кафе на Ленина",
                    "address": "ул. Ленина, 1",
                    "contact_name": "Дежурный",
                    "contact_phone": "+70000000000",
                }
            )
            return dict(platform.bump(request_id, status="accepted", contacts_disclosed=True))

        return await _mutation("accept", request_id, request, key, apply)

    @app.post("/api/v1/requests/{request_id}/decline")
    async def decline(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            card["assignment"]["state"] = "declined"
            card["assignment"]["decline_reason"] = body["reason"]
            return dict(platform.bump(request_id, status="action_required"))

        return await _mutation("decline", request_id, request, key, apply)

    @app.post("/api/v1/requests/{request_id}/withdraw")
    async def withdraw(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            card["assignment"]["state"] = "withdrawn"
            return dict(platform.bump(request_id, status="action_required"))

        return await _mutation("withdraw", request_id, request, key, apply)

    @app.post("/api/v1/requests/{request_id}/visit-proposals")
    async def visit_proposal(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            for old in card["visit_proposals"]:
                if old["status"] in {"pending", "approved"}:
                    old["status"] = "superseded"
            card["visit_proposals"].append(
                {
                    "id": f"vp_{next(platform._seq)}",
                    "assignment_id": body["assignment_id"],
                    "version": len(card["visit_proposals"]) + 1,
                    "visit_window_start": body.get("visit_window_start"),
                    "visit_window_end": body.get("visit_window_end"),
                    "price": {
                        "amount_minor": body.get("amount_minor"),
                        "currency": body.get("currency"),
                        "vat_mode": None,
                        "zero_cost_reason": body.get("zero_cost_reason"),
                        "is_known": body.get("amount_minor") is not None,
                    },
                    "scope_description": body.get("scope_description"),
                    "comment": None,
                    "access_requirements": None,
                    "valid_until": "2026-09-30T00:00:00Z",
                    "status": "pending",
                    "responded_at": None,
                    "response_comment": None,
                    "created_at": "2026-09-19T09:00:00Z",
                }
            )
            status = "accepted" if card["status"] == "scheduled" else card["status"]
            return dict(platform.bump(request_id, status=status))

        return await _mutation("visit_proposal", request_id, request, key, apply, status_code=201)

    @app.post("/api/v1/requests/{request_id}/repair-quotes")
    async def repair_quote(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            items = body.get("items") or []
            if body.get("amount_minor") != sum(i["amount_minor"] for i in items):
                return _error("VALIDATION_FAILED", "сумма позиций не равна сумме", 422)
            for old in card["repair_quotes"]:
                if old["status"] == "pending":
                    old["status"] = "superseded"
            card["repair_quotes"].append(
                {
                    "id": f"rq_{next(platform._seq)}",
                    "assignment_id": body["assignment_id"],
                    "version": len(card["repair_quotes"]) + 1,
                    "description_of_work": body["description_of_work"],
                    "price": {
                        "amount_minor": body.get("amount_minor"),
                        "currency": "RUB",
                        "vat_mode": None,
                        "zero_cost_reason": None,
                        "is_known": True,
                    },
                    "items": items,
                    "valid_until": "2026-09-30T00:00:00Z",
                    "status": "pending",
                    "responded_at": None,
                    "response_comment": None,
                    "created_at": "2026-09-19T09:00:00Z",
                }
            )
            return dict(platform.bump(request_id))

        return await _mutation("repair_quote", request_id, request, key, apply, status_code=201)

    @app.post("/api/v1/requests/{request_id}/start-work")
    async def start_work(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        return await _mutation(
            "start_work",
            request_id,
            request,
            key,
            lambda card, body: _transition(card, "scheduled", "in_progress"),
        )

    @app.post("/api/v1/requests/{request_id}/complete")
    async def complete(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            if card["status"] != "in_progress":
                return _error("INVALID_TRANSITION", f"недопустимо из {card['status']}", 409)
            card["completion_report"] = {
                "outcome": body["outcome"],
                "summary": body["summary"],
                "reported_at": f"2026-09-19T12:{next(platform._seq):02d}:00Z",
            }
            return _transition(card, "in_progress", "completion_reported")

        return await _mutation("complete", request_id, request, key, apply)

    @app.post("/api/v1/requests/{request_id}/cancellation-response")
    async def cancellation_response(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            cancellation = card.get("cancellation") or {}
            if cancellation.get("id") != body["cancellation_id"]:
                return _error("NOT_FOUND", "не найдено", 404)
            if cancellation["status"] != "pending":
                return _error("CANCELLATION_CLOSED", "Запрос отмены уже обработан", 409)
            cancellation["provider_response"] = body.get("comment")
            if body["decision"] == "accept":
                cancellation["status"] = "accepted"
                card["assignment"]["state"] = "revoked"
                return dict(platform.bump(request_id, status="cancelled"))
            if not body.get("comment"):
                return _error("VALIDATION_FAILED", "Укажите причину несогласия", 422)
            cancellation["status"] = "disputed"
            cancellation["disputed"] = True
            return dict(platform.bump(request_id, status=cancellation["previous_status"]))

        return await _mutation("cancellation_response", request_id, request, key, apply)

    @app.get("/api/v1/requests/{request_id}/messages")
    async def list_messages(request_id: str) -> Any:
        _count("list_messages")
        return {"items": platform.messages.get(request_id, []), "next_cursor": None}

    @app.post("/api/v1/requests/{request_id}/messages")
    async def send_message(
        request_id: str, request: Request, key: str | None = Header(None, alias="Idempotency-Key")
    ) -> Any:
        def apply(card: dict[str, Any], body: dict[str, Any]) -> Any:
            message = {
                "id": f"msg_{next(platform._seq)}",
                "request_id": request_id,
                "author_kind": "integration_client",
                "author_membership_id": None,
                "thread_provider_id": None,
                "body": body["body"],
                "created_at": "2026-09-19T09:00:00Z",
            }
            platform.messages[request_id].append(message)
            return message

        return await _mutation(
            "message", request_id, request, key, apply, status_code=201, check_version=False
        )

    @app.get("/api/v1/attachments/{attachment_id}/content")
    async def download_attachment(attachment_id: str) -> Any:
        _count("download_attachment")
        content = platform.attachments.get(attachment_id)
        if content is None:
            raise HTTPException(status_code=404)
        return Response(content=content, media_type="image/jpeg")

    @app.post("/api/v1/webhook-subscriptions")
    async def create_subscription(request: Request) -> Any:
        _count("create_subscription")
        body = await request.json()
        platform.subscription = {
            "id": f"whs_{platform.call_counts['create_subscription']}",
            "url": body["url"],
            "secret": "test-secret-value",
            "status": "active",
            "events": body.get("events", []),
        }
        return JSONResponse(platform.subscription, status_code=201)

    @app.get("/api/v1/webhook-subscriptions")
    async def list_subscriptions() -> Any:
        _count("list_subscriptions")
        if platform.fail_list_subscriptions:
            return _error("FORBIDDEN", "нет права webhooks:manage", 403)
        current = platform.subscription
        items = [] if current is None else [{k: v for k, v in current.items() if k != "secret"}]
        return {"items": items, "next_cursor": None, "has_more": False}

    @app.delete("/api/v1/webhook-subscriptions/{subscription_id}")
    async def delete_subscription(subscription_id: str) -> Any:
        _count("delete_subscription")
        platform.deleted_subscriptions.append(subscription_id)
        if platform.subscription is not None and platform.subscription["id"] == subscription_id:
            platform.subscription = None
        return Response(status_code=204)

    @app.get("/api/v1/events")
    async def get_events(cursor: str | None = None) -> Any:
        _count("get_events")
        if platform.cursor_expired and cursor is not None:
            return _error("CURSOR_EXPIRED", "курсор истёк", 409)
        start = int(cursor) if cursor else 0
        page = platform.events[start : start + 50]
        next_cursor = str(start + len(page)) if page else (cursor or "0")
        return {"events": page, "next_cursor": next_cursor, "has_more": False}

    return app


def make_envelope(
    *,
    event_id: str,
    event_type: str,
    resource_id: str,
    resource_version: int | None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "event_id": event_id,
        "type": event_type,
        "occurred_at": "2026-09-19T09:00:00Z",
        "recipient_organization_id": "org_provider_demo",
        "resource_id": resource_id,
        "resource_version": resource_version,
        "data": data or {},
    }


def signed_headers(
    secret: str, body: bytes, *, event_id: str, delivery_id: str, timestamp: int | None = None
) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    return {
        "X-Event-ID": event_id,
        "X-Delivery-ID": delivery_id,
        "X-Timestamp": str(ts),
        "X-Signature": sign(secret, ts, body),
        "Content-Type": "application/json",
    }
