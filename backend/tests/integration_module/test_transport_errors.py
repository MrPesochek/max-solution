import socket

import httpx
import pytest

from app.modules.integration import transport


def _outgoing(url: str) -> transport.OutgoingWebhook:
    return transport.OutgoingWebhook(
        url=url, secret="s", event_id="evt_1", delivery_id="dlv_1", body=b"{}", timestamp=0
    )


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_connection_refused_is_generic_network_error() -> None:
    outgoing = _outgoing(f"http://127.0.0.1:{_closed_port()}/hook")

    result = await transport.deliver(outgoing, timeout=2, private_hosts={("127.0.0.1", None)})

    assert result.outcome == "retryable"
    assert result.error == "network"


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("refused"), httpx.ReadError("reset"), httpx.RemoteProtocolError("x")],
)
async def test_network_error_class_not_exposed(
    monkeypatch: pytest.MonkeyPatch, exc: httpx.HTTPError
) -> None:
    async def failing(*args: object, **kwargs: object) -> None:
        raise exc

    monkeypatch.setattr(transport, "post_pinned", failing)

    result = await transport.deliver(_outgoing("https://crm.example.com/hook"), timeout=1)

    assert result.outcome == "retryable"
    assert result.error == "network"


async def test_unlisted_private_target_is_blocked() -> None:
    result = await transport.deliver(
        _outgoing("http://postgres:5432/"), timeout=1, private_hosts={("onec-connector", 8083)}
    )
    assert result.outcome == "blocked"
    assert result.error == "ssrf:scheme"
