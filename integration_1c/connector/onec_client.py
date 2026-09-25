from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from connector.settings import Settings

logger = logging.getLogger("onec_connector.onec")

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
EMPTY_REF = "00000000-0000-0000-0000-000000000000"
_ATTEMPTS = 3


class OneCError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str = "") -> None:
        super().__init__(f"1С: {status_code} {code} {message}".strip())
        self.message = message
        self.status_code = status_code
        self.code = code


class OneCUnreachableError(Exception):
    """Сеть/таймаут/5xx после повторов: веб-сервер или база 1С недоступны."""


def guid_literal(ref_key: str) -> str:
    if not _GUID_RE.match(ref_key):
        raise ValueError(f"не GUID: {ref_key!r}")
    return f"guid'{ref_key}'"


def string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def is_empty_ref(value: Any) -> bool:
    return not value or value == EMPTY_REF


class OneCClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.onec_odata_url.rstrip("/") + "/",
            auth=httpx.BasicAuth(settings.onec_username, settings.onec_password),
            timeout=settings.onec_timeout_seconds,
            verify=settings.verify_tls(),
            headers={"Accept": "application/json"},
            transport=transport,
        )
        self._retry_delay = min(1.0, settings.background_retry_base_delay_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        query = {"$format": "json", **(params or {})}
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                response = await self._client.request(method, path, params=query, json=json_body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == _ATTEMPTS:
                    raise OneCUnreachableError(str(exc)) from exc
                await asyncio.sleep(self._retry_delay * attempt)
                continue
            if response.status_code in {502, 503, 504}:
                if attempt == _ATTEMPTS:
                    raise OneCUnreachableError(f"HTTP {response.status_code}")
                await asyncio.sleep(self._retry_delay * attempt)
                continue
            if response.status_code >= 400:
                raise _to_error(response)
            return response
        raise AssertionError("unreachable")

    async def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        select: list[str] | None = None,
        top: int | None = None,
        orderby: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if filter:
            params["$filter"] = filter
        if select:
            params["$select"] = ",".join(select)
        if top is not None:
            params["$top"] = str(top)
        if orderby:
            params["$orderby"] = orderby
        response = await self._request("GET", entity, params=params)
        return [dict(item) for item in response.json().get("value", [])]

    async def get(self, entity: str, ref_key: str) -> dict[str, Any] | None:
        try:
            response = await self._request("GET", f"{entity}({guid_literal(ref_key)})")
        except OneCError as exc:
            if exc.status_code == 404:
                return None
            raise
        return _strip_metadata(response.json())

    async def create(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", entity, json_body=body)
        return _strip_metadata(response.json())

    async def update(self, entity: str, ref_key: str, body: dict[str, Any]) -> dict[str, Any]:
        """PATCH меняет только переданные реквизиты; табличная часть в теле заменяется
        целиком — поэтому её перед записью перечитывают и дополняют."""
        response = await self._request(
            "PATCH", f"{entity}({guid_literal(ref_key)})", json_body=body
        )
        return _strip_metadata(response.json())

    async def post_document(self, entity: str, ref_key: str) -> None:
        await self._request(
            "POST",
            f"{entity}({guid_literal(ref_key)})/Post()",
            params={"PostingModeOperational": "false"},
        )

    async def find_by(
        self, entity: str, field: str, value: str, *, select: list[str] | None = None
    ) -> dict[str, Any] | None:
        items = await self.query(
            entity,
            filter=f"{field} eq {string_literal(value)} and DeletionMark eq false",
            select=select,
            top=1,
        )
        return items[0] if items else None


def _strip_metadata(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if not k.startswith("odata.")}


def _to_error(response: httpx.Response) -> OneCError:
    code = ""
    message = response.text[:500]
    try:
        error = response.json().get("odata.error", {})
        code = str(error.get("code", ""))
        raw = error.get("message", {})
        message = str(raw.get("value", "")) if isinstance(raw, dict) else str(raw)
    except (ValueError, AttributeError):
        pass
    return OneCError(message, status_code=response.status_code, code=code)
