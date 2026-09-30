from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from connector.contract import (
    AcceptRequest,
    CancellationResponseRequest,
    CompleteRequest,
    DeclineRequest,
    ErrorEnvelope,
    EventsPage,
    MeResponse,
    MessageCreateRequest,
    Page,
    RepairQuote,
    RepairQuoteCreateRequest,
    RequestCard,
    RequestListItem,
    StartWorkRequest,
    VisitProposal,
    VisitProposalCreateRequest,
    WebhookEnvelope,
    WebhookSubscriptionResponse,
    WebhookSubscriptionsPage,
    WithdrawAssignmentRequest,
)

ME: dict[str, Any] = {
    "organization_id": "org_2yV6mWq1Kk0Zt7bQxHn3Pa",
    "organization_name": "ООО Сервис",
    "client_id": "ic_2yV6mWq1Kk0Zt7bQxHn3Pb",
    "client_name": "Коннектор 1С",
    "key_prefix": "9f1c4d2ab73e",
    "scopes": ["events:read", "requests:read", "webhooks:manage"],
}

SUBSCRIPTION_CREATED: dict[str, Any] = {
    "id": "whs_2yV6mWq1Kk0Zt7bQxHn3Pc",
    "url": "http://onec-connector:8083/webhooks/platform",
    "events": ["request.assigned", "request.changed"],
    "status": "active",
    "created_at": "2026-09-19T09:00:00Z",
    "disabled_at": None,
    "secret": "S5Yb2wC1nUq9xT0mJvP7kLdA8fGhR4eZ",
}

SUBSCRIPTIONS_PAGE: dict[str, Any] = {
    "items": [
        {
            "id": "whs_2yV6mWq1Kk0Zt7bQxHn3Pc",
            "url": "http://onec-connector:8083/webhooks/platform",
            "events": ["request.assigned"],
            "status": "active",
            "created_at": "2026-09-19T09:00:00Z",
            "disabled_at": None,
        }
    ],
    "next_cursor": None,
    "has_more": False,
}

EVENTS_PAGE: dict[str, Any] = {
    "events": [
        {
            "schema_version": "1",
            "event_id": "evt_2yV6mWq1Kk0Zt7bQxHn3Pd",
            "type": "request.assigned",
            "occurred_at": "2026-09-19T09:00:00Z",
            "recipient_organization_id": "org_2yV6mWq1Kk0Zt7bQxHn3Pa",
            "resource_id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe",
            "resource_version": 1,
            "data": {
                "request": {"id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe", "status": "awaiting_provider"}
            },
        },
        {
            "schema_version": "1",
            "event_id": "evt_2yV6mWq1Kk0Zt7bQxHn3Pf",
            "type": "assignment.revoked",
            "occurred_at": "2026-09-19T09:05:00Z",
            "recipient_organization_id": "org_2yV6mWq1Kk0Zt7bQxHn3Pa",
            "resource_id": "asg_2yV6mWq1Kk0Zt7bQxHn3Pg",
            "resource_version": None,
            "data": {"reason_kind": "customer_revoked"},
        },
    ],
    "next_cursor": "2",
    "has_more": True,
}

PING_ENVELOPE: dict[str, Any] = {
    "schema_version": "1",
    "event_id": "evt_2yV6mWq1Kk0Zt7bQxHn3Ph",
    "type": "ping",
    "occurred_at": "2026-09-19T09:10:00Z",
    "recipient_organization_id": "org_2yV6mWq1Kk0Zt7bQxHn3Pa",
    "resource_id": "whs_2yV6mWq1Kk0Zt7bQxHn3Pc",
    "resource_version": None,
    "data": {"test": True},
}


REQUEST_CARD: dict[str, Any] = {
    "id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe",
    "request_number": 123,
    "status": "scheduled",
    "route": "own_service",
    "urgency": "normal",
    "version": 5,
    "symptom_description": "Не морозит холодильная витрина",
    "error_code": None,
    "equipment": {
        "id": "eq_2yV6mWq1Kk0Zt7bQxHn3Pj",
        "category_id": "cat_2yV6mWq1Kk0Zt7bQxHn3Pk",
        "category_name": "холодильная витрина",
        "brand": "Полюс",
        "model": "ВХС-1",
        "serial_number": "SN-0001",
        "notes": None,
    },
    "location": {
        "id": "loc_2yV6mWq1Kk0Zt7bQxHn3Pl",
        "name": "Кафе на Ленина",
        "city_id": "city_2yV6mWq1Kk0Zt7bQxHn3Pm",
        "district_id": None,
        "address": "ул. Ленина, 1",
        "timezone": "Europe/Moscow",
        "contact_name": "Дежурный",
        "contact_phone": "+70000000000",
    },
    "contacts_disclosed": True,
    "photos_incomplete": False,
    "photos_incomplete_reason": None,
    "submitted_at": "2026-09-19T08:00:00Z",
    "created_at": "2026-09-19T08:00:00Z",
    "assignment": {
        "id": "asg_2yV6mWq1Kk0Zt7bQxHn3Pn",
        "request_id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe",
        "provider_organization_id": "org_provider_demo",
        "route": "own_service",
        "state": "accepted",
        "warranty_decision": "not_stated",
        "warranty_decision_comment": None,
        "field_worker": {
            "membership_id": None,
            "display_name": "Иван Мастеров",
            "contact_phone": "+79990000000",
            "stated_by_company": True,
        },
        "decline_reason": None,
        "revoke_reason": None,
        "withdrawal_reason": None,
        "expires_at": None,
        "responded_at": "2026-09-19T08:10:00Z",
        "created_at": "2026-09-19T08:00:00Z",
    },
    "visit_proposals": [
        {
            "id": "vp_2yV6mWq1Kk0Zt7bQxHn3Po",
            "assignment_id": "asg_2yV6mWq1Kk0Zt7bQxHn3Pn",
            "version": 1,
            "visit_window_start": "2026-09-20T10:00:00Z",
            "visit_window_end": "2026-09-20T13:00:00Z",
            "price": {
                "amount_minor": 150000,
                "currency": "RUB",
                "vat_mode": "not_applicable",
                "zero_cost_reason": None,
                "is_known": True,
            },
            "scope_description": "Диагностика и ремонт",
            "comment": None,
            "access_requirements": None,
            "valid_until": "2026-09-21T00:00:00Z",
            "status": "approved",
            "responded_at": "2026-09-19T09:00:00Z",
            "response_comment": None,
            "created_at": "2026-09-19T08:30:00Z",
        }
    ],
    "repair_quotes": [
        {
            "id": "rq_2yV6mWq1Kk0Zt7bQxHn3Pp",
            "assignment_id": "asg_2yV6mWq1Kk0Zt7bQxHn3Pn",
            "version": 1,
            "description_of_work": "Замена термостата",
            "price": {
                "amount_minor": None,
                "currency": None,
                "vat_mode": None,
                "zero_cost_reason": None,
                "is_known": False,
            },
            "valid_until": "2026-09-22T00:00:00Z",
            "status": "pending",
            "responded_at": None,
            "response_comment": None,
            "created_at": "2026-09-19T08:40:00Z",
        }
    ],
    "cancellation": None,
}

REQUEST_LIST_ITEM: dict[str, Any] = {
    "id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe",
    "request_number": 123,
    "status": "scheduled",
    "route": "own_service",
    "urgency": "normal",
    "version": 5,
    "location_id": "loc_2yV6mWq1Kk0Zt7bQxHn3Pl",
    "location_name": "Кафе на Ленина",
    "equipment_title": "Полюс ВХС-1",
    "symptom_description": "Не морозит холодильная витрина",
    "assignment_id": "asg_2yV6mWq1Kk0Zt7bQxHn3Pn",
    "assignment_state": "accepted",
    "provider_organization_id": "org_provider_demo",
    "updated_at": "2026-09-19T08:40:00Z",
    "created_at": "2026-09-19T08:00:00Z",
}

MESSAGES_PAGE: dict[str, Any] = {
    "items": [
        {
            "id": "msg_2yV6mWq1Kk0Zt7bQxHn3Pq",
            "request_id": "req_2yV6mWq1Kk0Zt7bQxHn3Pe",
            "author_kind": "integration_client",
            "author_membership_id": None,
            "body": "Уточните код ошибки",
            "created_at": "2026-09-19T09:05:00Z",
        }
    ],
    "next_cursor": None,
}

VISIT_PROPOSALS_LIST = REQUEST_CARD["visit_proposals"]
REPAIR_QUOTES_LIST = REQUEST_CARD["repair_quotes"]

ERROR_BODY: dict[str, Any] = {
    "error": {
        "code": "VERSION_CONFLICT",
        "message": "Заявка изменена",
        "request_id": "r-abc123",
        "details": {"current_version": 8},
    }
}


def test_me_response() -> None:
    parsed = MeResponse.model_validate(ME)
    assert parsed.organization_id.startswith("org_")
    assert "webhooks:manage" in parsed.scopes


def test_subscription_create_response() -> None:
    parsed = WebhookSubscriptionResponse.model_validate(SUBSCRIPTION_CREATED)
    assert parsed.secret
    assert parsed.status == "active"


def test_subscriptions_page_has_no_secret() -> None:
    parsed = WebhookSubscriptionsPage.model_validate(SUBSCRIPTIONS_PAGE)
    assert parsed.has_more is False
    assert "secret" not in parsed.items[0].model_dump()


def test_events_page_and_nullable_version() -> None:
    parsed = EventsPage.model_validate(EVENTS_PAGE)
    assert parsed.next_cursor == "2"
    assert parsed.has_more is True
    assert parsed.events[0].resource_version == 1
    assert parsed.events[1].resource_version is None


def test_ping_envelope_is_accepted() -> None:
    parsed = WebhookEnvelope.model_validate(PING_ENVELOPE)
    assert parsed.type == "ping"
    assert parsed.data == {"test": True}


def test_request_card_shape() -> None:
    parsed = RequestCard.model_validate(REQUEST_CARD)
    assert parsed.equipment.brand == "Полюс"
    assert parsed.location.address == "ул. Ленина, 1"
    assert parsed.assignment.field_worker is not None
    assert parsed.assignment.field_worker.display_name == "Иван Мастеров"
    assert parsed.visit_proposals[0].price.amount_minor == 150000
    assert parsed.visit_proposals[0].price.is_known is True
    assert parsed.repair_quotes[0].price.is_known is False
    assert parsed.repair_quotes[0].description_of_work == "Замена термостата"
    assert parsed.cancellation is None


def test_request_list_item_shape() -> None:
    parsed = RequestListItem.model_validate(REQUEST_LIST_ITEM)
    assert parsed.equipment_title == "Полюс ВХС-1"
    assert parsed.assignment_state == "accepted"


def test_requests_page_has_no_has_more() -> None:
    page = Page.model_validate({"items": [REQUEST_LIST_ITEM], "next_cursor": None})
    assert "has_more" not in page.model_dump()


def test_messages_page_shape() -> None:
    page = Page.model_validate(MESSAGES_PAGE)
    assert page.items[0]["body"] == "Уточните код ошибки"
    assert page.items[0]["author_kind"] == "integration_client"


def test_visit_proposals_and_repair_quotes_are_plain_lists() -> None:
    proposals = [VisitProposal.model_validate(p) for p in VISIT_PROPOSALS_LIST]
    quotes = [RepairQuote.model_validate(q) for q in REPAIR_QUOTES_LIST]
    assert proposals[0].scope_description == "Диагностика и ремонт"
    assert quotes[0].status == "pending"


def test_error_body_shape() -> None:
    parsed = ErrorEnvelope.model_validate(ERROR_BODY)
    assert parsed.error.code == "VERSION_CONFLICT"
    assert parsed.error.details["current_version"] == 8


OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "integration-api.json"


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    return dict(json.loads(OPENAPI_PATH.read_text(encoding="utf-8")))


def _validator(document: dict[str, Any], schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator({**schema, "components": document["components"]})


def _response_schema(
    document: dict[str, Any], path: str, method: str, status: str
) -> dict[str, Any]:
    operation = document["paths"][path][method]
    response = operation["responses"][status]
    return dict(response["content"]["application/json"]["schema"])


@pytest.mark.parametrize(
    ("path", "method", "status", "sample"),
    [
        ("/me", "get", "200", ME),
        ("/webhook-subscriptions", "post", "201", SUBSCRIPTION_CREATED),
        ("/webhook-subscriptions", "get", "200", SUBSCRIPTIONS_PAGE),
        ("/events", "get", "200", EVENTS_PAGE),
        ("/requests/{request_id}", "get", "200", REQUEST_CARD),
        ("/requests", "get", "200", {"items": [REQUEST_LIST_ITEM], "next_cursor": None}),
        ("/requests/{request_id}/messages", "get", "200", MESSAGES_PAGE),
        ("/requests/{request_id}/visit-proposals", "get", "200", VISIT_PROPOSALS_LIST),
        ("/requests/{request_id}/repair-quotes", "get", "200", REPAIR_QUOTES_LIST),
        ("/requests/{request_id}/accept", "post", "409", ERROR_BODY),
    ],
)
def test_sample_matches_platform_openapi(
    openapi: dict[str, Any], path: str, method: str, status: str, sample: Any
) -> None:
    schema = _response_schema(openapi, path, method, status)
    errors = sorted(_validator(openapi, schema).iter_errors(sample), key=str)
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


@pytest.mark.parametrize("envelope", [PING_ENVELOPE, *EVENTS_PAGE["events"]])
def test_webhook_envelope_matches_platform_openapi(
    openapi: dict[str, Any], envelope: dict[str, Any]
) -> None:
    schema = {"$ref": "#/components/schemas/EventEnvelopeView"}
    errors = list(_validator(openapi, schema).iter_errors(envelope))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize(
    ("schema_name", "model", "sample"),
    [
        ("AcceptRequestBody", AcceptRequest, {"assignment_id": "asg_1", "expected_version": 3}),
        (
            "DeclineRequestBody",
            DeclineRequest,
            {"assignment_id": "asg_1", "reason": "Нет запчастей", "expected_version": 3},
        ),
        (
            "VisitProposalBody",
            VisitProposalCreateRequest,
            {
                "assignment_id": "asg_1",
                "visit_window_start": "2026-09-30T10:00:00+03:00",
                "visit_window_end": "2026-09-30T12:00:00+03:00",
                "amount_minor": 150000,
                "currency": "RUB",
                "scope_description": "Выезд мастера (диагностика)",
                "expected_version": 3,
            },
        ),
        (
            "RepairQuoteBody",
            RepairQuoteCreateRequest,
            {
                "assignment_id": "asg_1",
                "description_of_work": "Смета по заказ-наряду ЗН00-000001",
                "items": [{"title": "Замена термостата", "amount_minor": 320050}],
                "amount_minor": 320050,
                "currency": "RUB",
                "expected_version": 3,
            },
        ),
        ("StartWorkBody", StartWorkRequest, {"assignment_id": "asg_1", "expected_version": 3}),
        (
            "CompleteWorkBody",
            CompleteRequest,
            {
                "assignment_id": "asg_1",
                "outcome": "resolved",
                "summary": "Работы выполнены",
                "expected_version": 3,
            },
        ),
        (
            "WithdrawAssignmentBody",
            WithdrawAssignmentRequest,
            {"assignment_id": "asg_1", "reason": "Отказ исполнителя", "expected_version": 3},
        ),
        (
            "CancellationResponseBody",
            CancellationResponseRequest,
            {
                "assignment_id": "asg_1",
                "cancellation_id": "can_1",
                "decision": "decline",
                "comment": "Мастер уже выехал",
                "expected_version": 3,
            },
        ),
        (
            "MessageCreateBody",
            MessageCreateRequest,
            {"body": "Уточните код", "assignment_id": "asg_1"},
        ),
    ],
)
def test_mutation_bodies_match_platform_openapi(
    openapi: dict[str, Any], schema_name: str, model: Any, sample: dict[str, Any]
) -> None:
    body = model.model_validate(sample).model_dump(mode="json", exclude_none=True)
    schema = {"$ref": f"#/components/schemas/{schema_name}"}
    errors = list(_validator(openapi, schema).iter_errors(body))
    assert not errors, [e.message for e in errors]
