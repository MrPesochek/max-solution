import http.server
import socket
import threading
import time
from collections.abc import Iterator
from typing import ClassVar

import httpx
import pytest

from app.infra.net import ssrf
from app.infra.net.ssrf import (
    SsrfValidationError,
    post_pinned,
    resolve_listed_ips,
    resolve_public_ips,
    validate_webhook_url,
)

CONNECTOR = frozenset({("onec-connector", 8083)})


def test_https_default_port_allowed() -> None:
    validate_webhook_url("https://example.com/webhook")


def test_http_rejected_for_unlisted_host() -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url("http://example.com/webhook", private_hosts=CONNECTOR)


def test_http_and_port_allowed_for_listed_host() -> None:
    validate_webhook_url("http://onec-connector:8083/webhooks/platform", private_hosts=CONNECTOR)


def test_listed_host_with_other_port_is_not_listed() -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url("http://onec-connector:5432/", private_hosts=CONNECTOR)


def test_listed_host_without_port_allows_any_port() -> None:
    validate_webhook_url("http://crm.lan:9000/hook", private_hosts={("crm.lan", None)})


def test_custom_port_rejected_for_unlisted_host() -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url("https://example.com:8443/webhook", private_hosts=CONNECTOR)


def test_userinfo_rejected() -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url("https://user:pass@example.com/webhook")


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
    ],
)
def test_forbidden_ip_literals_rejected(host: str) -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url(f"https://{host}/webhook", private_hosts=CONNECTOR)


@pytest.mark.parametrize(
    "host",
    [
        "[::1]",
        "[fc00::1]",
        "[::ffff:127.0.0.1]",
    ],
)
def test_forbidden_ipv6_literals_rejected(host: str) -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url(f"https://{host}/webhook")


def test_listed_ip_literal_allowed() -> None:
    validate_webhook_url("http://10.0.0.5:8083/hook", private_hosts={("10.0.0.5", 8083)})
    validate_webhook_url("http://127.0.0.1:9000/hook", private_hosts={("127.0.0.1", None)})


@pytest.mark.parametrize(
    "host",
    ["169.254.169.254", "169.254.1.1", "100.100.100.200", "0.0.0.0", "224.0.0.1"],
)
def test_metadata_and_link_local_rejected_even_when_listed(host: str) -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url(f"http://{host}/latest/meta-data", private_hosts={(host, None)})


def test_metadata_ipv6_rejected_even_when_listed() -> None:
    with pytest.raises(SsrfValidationError):
        validate_webhook_url("http://[fd00:ec2::254]/", private_hosts={("fd00:ec2::254", None)})


def test_resolve_public_ips_accepts_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: object, **kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert resolve_public_ips("example.com") == ["93.184.216.34"]


def test_resolve_public_ips_rejects_if_any_address_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, port: object, **kwargs: object) -> list[tuple]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SsrfValidationError):
        resolve_public_ips("evil.example.com")


def test_resolve_public_ips_dns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: object, **kwargs: object) -> list[tuple]:
        raise socket.gaierror("не удалось разрешить имя")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SsrfValidationError):
        resolve_public_ips("nowhere.invalid")


def _fake_dns(monkeypatch: pytest.MonkeyPatch, *ips: str) -> None:
    def fake_getaddrinfo(host: str, port: object, **kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_resolve_listed_ips_accepts_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_dns(monkeypatch, "172.30.57.20")
    assert resolve_listed_ips("onec-connector") == ["172.30.57.20"]


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "100.100.100.200"])
def test_resolve_listed_ips_rejects_loopback_and_metadata(
    monkeypatch: pytest.MonkeyPatch, ip: str
) -> None:
    _fake_dns(monkeypatch, "172.30.57.20", ip)
    with pytest.raises(SsrfValidationError):
        resolve_listed_ips("onec-connector")


class _Handler(http.server.BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, object]]] = []
    response_body = b"ok-response"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _Handler.received.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[http.server.HTTPServer]:
    _Handler.received = []
    _Handler.response_body = b"ok-response"
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


async def test_post_pinned_reaches_local_server_with_original_host(
    local_server: http.server.HTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ssrf, "resolve_listed_ips", lambda host: ["127.0.0.1"])
    port = local_server.server_address[1]
    response = await post_pinned(
        f"http://localhost:{port}/hook",
        body=b'{"x":1}',
        headers={"X-Test": "1"},
        timeout=5,
        private_hosts={("localhost", port)},
    )
    assert response.status_code == 200
    assert response.body == b"ok-response"
    assert len(_Handler.received) == 1
    received = _Handler.received[0]
    assert received["path"] == "/hook"
    assert received["body"] == b'{"x":1}'
    headers = received["headers"]
    assert headers["Host"].startswith("localhost")
    assert headers["X-Test"] == "1"


async def test_post_pinned_truncates_large_response(local_server: http.server.HTTPServer) -> None:
    _Handler.response_body = b"x" * 1000
    port = local_server.server_address[1]
    response = await post_pinned(
        f"http://127.0.0.1:{port}/hook",
        body=b"",
        timeout=5,
        private_hosts={("127.0.0.1", port)},
        max_response_bytes=100,
    )
    assert response.truncated is True
    assert len(response.body) == 100


async def test_post_pinned_rejects_unlisted_private_ip(
    local_server: http.server.HTTPServer,
) -> None:
    port = local_server.server_address[1]
    with pytest.raises(SsrfValidationError):
        await post_pinned(
            f"http://127.0.0.1:{port}/hook",
            body=b"x",
            timeout=5,
            private_hosts={("onec-connector", 8083)},
        )
    assert _Handler.received == []


async def test_post_pinned_rejects_listed_name_resolving_to_loopback(
    local_server: http.server.HTTPServer,
) -> None:
    port = local_server.server_address[1]
    with pytest.raises(SsrfValidationError):
        await post_pinned(
            f"http://localhost:{port}/hook",
            body=b"x",
            timeout=5,
            private_hosts={("localhost", port)},
        )
    assert _Handler.received == []


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        try:
            for _ in range(100):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


async def test_post_pinned_has_overall_deadline() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(httpx.TimeoutException):
            await post_pinned(
                f"http://127.0.0.1:{server.server_address[1]}/hook",
                body=b"",
                timeout=0.5,
                private_hosts={("127.0.0.1", None)},
            )
        assert time.monotonic() - started < 3
    finally:
        server.shutdown()
        thread.join(timeout=2)
