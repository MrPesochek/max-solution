from typing import Annotated, Any

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.adapters.http.idempotency import idempotency_key_header, make_idempotency
from app.adapters.integration_api.rate_limit import (
    RateLimitExceeded,
    TokenBucketLimiter,
    headers_of,
)
from app.core.actor import IntegrationActor
from app.core.errors import Unauthenticated
from app.core.pipeline import Idempotency
from app.infra.config import get_settings
from app.modules.integration import api as integration
from app.modules.integration import policy

SECURITY_SCHEME = "bearer"

_bearer = HTTPBearer(
    scheme_name=SECURITY_SCHEME,
    bearerFormat="rk_<env>_<prefix>_<secret>",
    description="Ключ интеграции сервисной компании: `Authorization: Bearer <ключ>`.",
    auto_error=False,
)
_limiter: TokenBucketLimiter | None = None
_auth_failures: TokenBucketLimiter | None = None
_auth_failures_by_ip: TokenBucketLimiter | None = None


def get_limiter() -> TokenBucketLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = TokenBucketLimiter(
            rate_per_second=settings.integration_rate_limit_rps,
            burst=settings.integration_rate_limit_burst,
        )
    return _limiter


def get_auth_failure_limiter() -> TokenBucketLimiter:
    global _auth_failures
    if _auth_failures is None:
        settings = get_settings()
        _auth_failures = TokenBucketLimiter(
            rate_per_second=settings.integration_auth_failure_rps,
            burst=settings.integration_auth_failure_burst,
        )
    return _auth_failures


def get_ip_auth_failure_limiter() -> TokenBucketLimiter:
    global _auth_failures_by_ip
    if _auth_failures_by_ip is None:
        settings = get_settings()
        _auth_failures_by_ip = TokenBucketLimiter(
            rate_per_second=settings.integration_auth_failure_ip_rps,
            burst=settings.integration_auth_failure_ip_burst,
        )
    return _auth_failures_by_ip


def reset_limiter() -> None:
    global _limiter, _auth_failures, _auth_failures_by_ip
    _limiter = None
    _auth_failures = None
    _auth_failures_by_ip = None


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _failure_key(ip: str, raw: str) -> str:
    parsed = integration.parse_api_key(raw)
    return f"{ip}:{parsed.prefix if parsed is not None else '-'}"


async def current_integration_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> IntegrationActor:
    raw = credentials.credentials.strip() if credentials is not None else ""
    ip = _client_ip(request)
    pair_key = _failure_key(ip, raw)
    by_pair = get_auth_failure_limiter()
    by_ip = get_ip_auth_failure_limiter()
    decision = by_pair.check(pair_key)
    if not decision.allowed:
        raise RateLimitExceeded(decision)
    ip_decision = by_ip.check(ip)
    if not ip_decision.allowed:
        by_pair.refund(pair_key)
        raise RateLimitExceeded(ip_decision)
    failed = False
    try:
        if not raw:
            raise Unauthenticated("Требуется ключ интеграции", code="API_KEY_INVALID")
        return await integration.authenticate_api_key(raw)
    except Unauthenticated:
        failed = True
        raise
    finally:
        if not failed:
            by_pair.refund(pair_key)
            by_ip.refund(ip)


async def rate_limited_actor(
    response: Response,
    actor: Annotated[IntegrationActor, Depends(current_integration_actor)],
) -> IntegrationActor:
    decision = get_limiter().check(str(actor.integration_client_id))
    response.headers.update(headers_of(decision))
    if not decision.allowed:
        raise RateLimitExceeded(decision)
    return actor


class RequireScope:
    def __init__(self, *scopes: str) -> None:
        unknown = [s for s in scopes if s not in policy.SCOPES]
        if unknown:
            raise ValueError(f"неизвестный scope: {unknown}")
        self.scopes = scopes

    async def __call__(
        self, actor: Annotated[IntegrationActor, Depends(rate_limited_actor)]
    ) -> IntegrationActor:
        policy.require_scope(actor, *self.scopes)
        return actor


class CommandIdempotency:
    def __init__(self, key: str, operation: str) -> None:
        self.key = key
        self.operation = operation

    def of(self, body: BaseModel | dict[str, Any] | None = None) -> Idempotency:
        payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
        return make_idempotency(self.key, self.operation, payload or {})


def command_idempotency(
    request: Request, key: Annotated[str, Depends(idempotency_key_header)]
) -> CommandIdempotency:
    path = request.url.path
    root = request.scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root) :]
    return CommandIdempotency(key, f"{request.method} {path}")


AnyKey = Annotated[IntegrationActor, Depends(RequireScope())]
RequestsRead = Annotated[IntegrationActor, Depends(RequireScope("requests:read"))]
RequestsWrite = Annotated[IntegrationActor, Depends(RequireScope("requests:write"))]
MessageWrite = Annotated[
    IntegrationActor, Depends(RequireScope("requests:write", "marketplace:write"))
]
MarketplaceRead = Annotated[IntegrationActor, Depends(RequireScope("marketplace:read"))]
MarketplaceWrite = Annotated[IntegrationActor, Depends(RequireScope("marketplace:write"))]
AttachmentRead = Annotated[
    IntegrationActor, Depends(RequireScope("requests:read", "marketplace:read"))
]
EquipmentRead = Annotated[IntegrationActor, Depends(RequireScope("equipment:read"))]
BindingsRead = Annotated[IntegrationActor, Depends(RequireScope("service_bindings:read"))]
BindingsWrite = Annotated[IntegrationActor, Depends(RequireScope("service_bindings:write"))]
ReviewsRead = Annotated[IntegrationActor, Depends(RequireScope("reviews:read"))]
ReviewsWrite = Annotated[IntegrationActor, Depends(RequireScope("reviews:write"))]
WebhooksManage = Annotated[IntegrationActor, Depends(RequireScope("webhooks:manage"))]
EventsRead = Annotated[IntegrationActor, Depends(RequireScope("events:read"))]

Idem = Annotated[CommandIdempotency, Depends(command_idempotency)]
