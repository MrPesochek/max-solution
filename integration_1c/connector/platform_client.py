from __future__ import annotations

import asyncio
import hashlib
import json
import random
import uuid
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from connector.contract import (
    ErrorEnvelope,
    EventsPage,
    FormerAssignmentCard,
    MessageItem,
    RequestCard,
    RequestListItem,
    WebhookSubscriptionResponse,
    WebhookSubscriptionsPage,
)
from connector.settings import Settings

Method = Literal["GET", "POST", "DELETE"]

SECRET_NOT_REPLAYABLE = "IDEMPOTENT_SECRET_NOT_REPLAYABLE"
_ROTATE_ATTEMPTS = 3


class PlatformApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        self.details = details or {}


class VersionConflictError(PlatformApiError):
    @property
    def current_version(self) -> int | None:
        value = self.details.get("current_version")
        return int(value) if isinstance(value, int) else None


class PlatformUnreachableError(Exception):
    pass


class PlatformContractError(Exception):
    def __init__(self, what: str, errors: list[str]) -> None:
        super().__init__(f"ответ платформы {what} не совпадает с контрактом: {'; '.join(errors)}")
        self.what = what
        self.errors = errors


def _validate(model: type[BaseModel], payload: Any, what: str) -> dict[str, Any]:
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in err['loc']) or '<корень>'}: {err['type']}"
            for err in exc.errors()[:10]
        ]
        raise PlatformContractError(what, errors) from exc
    return dict(payload)


class _ListPage(BaseModel):
    items: list[RequestListItem]
    next_cursor: str | None = None


class _MessagesPage(BaseModel):
    items: list[MessageItem]
    next_cursor: str | None = None


def idempotency_key(action: str, request_id: str, **fields: Any) -> str:
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{action}|{request_id}|{canonical}".encode()).hexdigest()
    return f"onec-connector:{action}:{digest[:32]}"


def operation_key(action: str) -> str:
    return f"onec-connector:{action}:{uuid.uuid4().hex}"


class PlatformClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.platform_api_base_url,
            timeout=settings.http_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.platform_api_key}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: Method,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idem_key: str | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if idem_key is not None:
            headers["Idempotency-Key"] = idem_key

        attempts = max(1, self._settings.background_retry_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                    headers=headers,
                    files=files,
                    data=data,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == attempts:
                    raise PlatformUnreachableError(str(exc)) from exc
                await self._sleep_backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = _to_api_error(response)
                if attempt == attempts:
                    raise last_error
                await self._sleep_backoff(attempt, response=response)
                continue

            if response.status_code >= 400:
                raise _to_api_error(response)

            return response

        raise last_error or RuntimeError("повторы запроса исчерпаны без ответа")

    async def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        retry_after = None
        if response is not None:
            header = response.headers.get("Retry-After")
            if header is not None:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
        base = self._settings.background_retry_base_delay_seconds
        delay = retry_after if retry_after is not None else base * (2 ** (attempt - 1))
        delay += random.uniform(0, base)
        await asyncio.sleep(delay)

    async def get_me(self) -> dict[str, Any]:
        response = await self._request("GET", "/me")
        return dict(response.json())

    async def list_requests(
        self, *, status: str | None = None, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        response = await self._request("GET", "/requests", params=params)
        return _validate(_ListPage, response.json(), "GET /requests")

    async def get_request(self, request_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/requests/{request_id}")
        payload = response.json()
        if isinstance(payload, dict) and "status" not in payload:
            return _validate(FormerAssignmentCard, payload, "GET /requests/{id}")
        return _validate(RequestCard, payload, "GET /requests/{id}")

    async def set_external_reference(
        self, request_id: str, external_id: str, *, expected_version: int
    ) -> dict[str, Any]:
        body = {"external_id": external_id, "expected_version": expected_version}
        key = idempotency_key("external-reference", request_id, **body)
        response = await self._request(
            "POST",
            f"/requests/{request_id}/external-reference",
            json_body=body,
            idem_key=key,
        )
        return dict(response.json())

    async def list_messages(self, request_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/requests/{request_id}/messages")
        return _validate(_MessagesPage, response.json(), "GET /requests/{id}/messages")

    async def request_action(
        self, request_id: str, action: str, body: dict[str, Any], *, idem_key: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST", f"/requests/{request_id}/{action}", json_body=body, idem_key=idem_key
        )
        return dict(response.json())

    async def download_attachment(self, attachment_id: str) -> tuple[bytes, str]:
        response = await self._request("GET", f"/attachments/{attachment_id}/content")
        return response.content, response.headers.get("content-type", "application/octet-stream")

    async def create_webhook_subscription(self, *, url: str, events: list[str]) -> dict[str, Any]:
        key = idempotency_key("webhook-subscription-create", url, events=events)
        try:
            response = await self._request(
                "POST",
                "/webhook-subscriptions",
                json_body={"url": url, "events": events},
                idem_key=key,
            )
        except PlatformApiError as exc:
            if exc.code != SECRET_NOT_REPLAYABLE:
                raise
            existing = await self._find_subscription(url)
            if existing is None:
                raise
            return await self.rotate_subscription_secret(str(existing["id"]))
        return _validate(
            WebhookSubscriptionResponse, response.json(), "POST /webhook-subscriptions"
        )

    async def _find_subscription(self, url: str) -> dict[str, Any] | None:
        listing = await self.list_webhook_subscriptions()
        matches = [item for item in listing.get("items", []) if item.get("url") == url]
        active = [item for item in matches if item.get("status") == "active"]
        found = (active or matches)[:1]
        return dict(found[0]) if found else None

    async def list_webhook_subscriptions(self) -> dict[str, Any]:
        response = await self._request("GET", "/webhook-subscriptions")
        return _validate(WebhookSubscriptionsPage, response.json(), "GET /webhook-subscriptions")

    async def delete_webhook_subscription(self, subscription_id: str) -> None:
        await self._request(
            "DELETE",
            f"/webhook-subscriptions/{subscription_id}",
            idem_key=operation_key("webhook-subscription-delete"),
        )

    async def rotate_subscription_secret(self, subscription_id: str) -> dict[str, Any]:
        for attempt in range(1, _ROTATE_ATTEMPTS + 1):
            key = operation_key("webhook-subscription-rotate")
            try:
                response = await self._request(
                    "POST",
                    f"/webhook-subscriptions/{subscription_id}/rotate-secret",
                    json_body={},
                    idem_key=key,
                )
            except PlatformApiError as exc:
                if exc.code != SECRET_NOT_REPLAYABLE or attempt == _ROTATE_ATTEMPTS:
                    raise
                continue
            return _validate(
                WebhookSubscriptionResponse, response.json(), "POST /webhook-subscriptions/rotate"
            )
        raise RuntimeError("ротация секрета не вернула ответа")

    async def get_events(self, *, cursor: str | None) -> dict[str, Any]:
        params = {"cursor": cursor} if cursor else {}
        response = await self._request("GET", "/events", params=params)
        return _validate(EventsPage, response.json(), "GET /events")


def _to_api_error(response: httpx.Response) -> PlatformApiError:
    request_id = response.headers.get("X-Request-ID")
    try:
        envelope = ErrorEnvelope.model_validate(response.json())
    except Exception:
        cls = VersionConflictError if response.status_code == 409 else PlatformApiError
        return cls(
            code=f"HTTP_{response.status_code}",
            message=response.text[:500],
            status_code=response.status_code,
            request_id=request_id,
        )
    body = envelope.error
    cls = VersionConflictError if body.code == "VERSION_CONFLICT" else PlatformApiError
    return cls(
        code=body.code,
        message=body.message,
        status_code=response.status_code,
        request_id=body.request_id or request_id,
        details=body.details,
    )
