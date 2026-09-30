import hmac
import ipaddress
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.clock import utcnow
from app.infra.config import Settings, get_settings
from app.modules.ops import api as ops

OPS_TOKEN_HEADER = "X-Ops-Token"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(raw: str) -> tuple[Network, ...]:
    try:
        return tuple(
            ipaddress.ip_network(item.strip(), strict=False)
            for item in raw.split(",")
            if item.strip()
        )
    except ValueError as exc:
        raise ValueError(f"OPS_ALLOWED_NETWORKS: {exc}") from exc


def _presented_token(request: Request) -> str | None:
    header = request.headers.get(OPS_TOKEN_HEADER)
    if header:
        return header
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def is_allowed(request: Request, settings: Settings, networks: Sequence[Network]) -> bool:
    presented = _presented_token(request)
    if settings.ops_token and presented is not None:
        return hmac.compare_digest(presented.encode(), settings.ops_token.encode())
    host = request.client.host if request.client is not None else None
    if host is None:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in networks)


def build_ops_router() -> APIRouter:
    settings = get_settings()
    networks = parse_networks(settings.ops_allowed_networks)
    router = APIRouter(prefix="/ops", include_in_schema=False)

    def guard(request: Request) -> None:
        if not is_allowed(request, get_settings(), networks):
            raise HTTPException(status_code=404)

    @router.get("/status")
    async def status(request: Request) -> JSONResponse:
        guard(request)
        snapshot = await ops.collect_status(utcnow(), get_settings())
        return JSONResponse(snapshot.to_json(), headers={"Cache-Control": "no-store"})

    @router.get("/metrics")
    async def metrics(request: Request) -> PlainTextResponse:
        guard(request)
        snapshot = await ops.collect_status(utcnow(), get_settings())
        return PlainTextResponse(
            ops.render_prometheus(snapshot),
            media_type="text/plain; version=0.0.4",
            headers={"Cache-Control": "no-store"},
        )

    return router
