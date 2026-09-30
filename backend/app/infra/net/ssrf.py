from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_METADATA_ADDRESSES = frozenset(
    {ipaddress.ip_address("fd00:ec2::254"), ipaddress.ip_address("100.100.100.200")}
)

_IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
PrivateHosts = Collection[tuple[str, int | None]]


class SsrfValidationError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _is_forbidden(ip: _IpAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_forbidden(ip.ipv4_mapped)
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _is_always_forbidden(ip: _IpAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_always_forbidden(ip.ipv4_mapped)
    return bool(
        ip in _METADATA_ADDRESSES
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _is_loopback(ip: _IpAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _is_listed(host: str, port: int, private_hosts: PrivateHosts) -> bool:
    return (host, port) in private_hosts or (host, None) in private_hosts


def _ip_literal(host: str) -> _IpAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _check_listed_literal(ip: _IpAddress) -> None:
    if _is_always_forbidden(ip):
        raise SsrfValidationError("ip_literal")


def _split(url: str, private_hosts: PrivateHosts) -> tuple[SplitResult, str, int, bool]:
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http"):
        raise SsrfValidationError("scheme")
    if not parsed.hostname:
        raise SsrfValidationError("host")
    if parsed.username is not None or parsed.password is not None:
        raise SsrfValidationError("userinfo")
    try:
        port = parsed.port or _default_port(parsed.scheme)
    except ValueError as exc:
        raise SsrfValidationError("port") from exc
    host = parsed.hostname
    return parsed, host, port, _is_listed(host, port, private_hosts)


def validate_webhook_url(url: str, *, private_hosts: PrivateHosts = ()) -> None:
    parsed, host, port, listed = _split(url, private_hosts)
    if not listed and parsed.scheme != "https":
        raise SsrfValidationError("scheme")
    if not listed and port != 443:
        raise SsrfValidationError("port")

    literal = _ip_literal(host)
    if literal is None:
        return
    if listed:
        _check_listed_literal(literal)
    elif _is_forbidden(literal):
        raise SsrfValidationError("ip_literal")


def _resolve_any(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfValidationError("dns_error") from exc
    ips: list[str] = []
    for info in infos:
        raw_ip = str(info[4][0])
        ip = str(ipaddress.ip_address(raw_ip.split("%")[0]))
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise SsrfValidationError("dns_error")
    ips.sort(key=lambda ip: ipaddress.ip_address(ip).version)
    return ips


def resolve_public_ips(host: str) -> list[str]:
    ips = _resolve_any(host)
    for raw_ip in ips:
        if _is_forbidden(ipaddress.ip_address(raw_ip)):
            raise SsrfValidationError("private_ip")
    return ips


def resolve_listed_ips(host: str) -> list[str]:
    ips = _resolve_any(host)
    for raw_ip in ips:
        ip = ipaddress.ip_address(raw_ip)
        if _is_always_forbidden(ip) or _is_loopback(ip):
            raise SsrfValidationError("private_ip")
    return ips


@dataclass(frozen=True)
class PinnedResponse:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False


def _format_authority(ip: str, port: int) -> str:
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


async def post_pinned(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    private_hosts: PrivateHosts = (),
    max_response_bytes: int = 64 * 1024,
) -> PinnedResponse:
    try:
        async with asyncio.timeout(timeout):
            return await _post_pinned(
                url,
                body=body,
                headers=headers,
                timeout=timeout,
                private_hosts=private_hosts,
                max_response_bytes=max_response_bytes,
            )
    except TimeoutError as exc:
        raise httpx.TimeoutException("общий дедлайн доставки истёк") from exc


async def _post_pinned(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str] | None,
    timeout: float,
    private_hosts: PrivateHosts,
    max_response_bytes: int,
) -> PinnedResponse:
    validate_webhook_url(url, private_hosts=private_hosts)
    parsed, host, port, listed = _split(url, private_hosts)

    literal = _ip_literal(host)
    if literal is not None:
        ips = [host]
    else:
        resolver = resolve_listed_ips if listed else resolve_public_ips
        ips = await asyncio.to_thread(resolver, host)

    pinned_authority = _format_authority(ips[0], port)
    path = parsed.path or "/"
    pinned_url = urlunsplit((parsed.scheme, pinned_authority, path, parsed.query, ""))

    request_headers = dict(headers or {})
    request_headers["Host"] = f"{host}:{port}" if port not in (80, 443) else host
    extensions: dict[str, object] = {"sni_hostname": host} if parsed.scheme == "https" else {}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        request = client.build_request(
            "POST", pinned_url, content=body, headers=request_headers, extensions=extensions
        )
        response = await client.send(request, stream=True)
        try:
            chunks: list[bytes] = []
            total = 0
            truncated = False
            async for chunk in response.aiter_bytes():
                if total >= max_response_bytes:
                    truncated = True
                    break
                remaining = max_response_bytes - total
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total += remaining
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
            response_body = b"".join(chunks)
        finally:
            await response.aclose()

    return PinnedResponse(
        status_code=response.status_code,
        body=response_body,
        headers=dict(response.headers),
        truncated=truncated,
    )
