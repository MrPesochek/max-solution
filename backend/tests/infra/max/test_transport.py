from typing import Any

import httpx
import pytest
import respx
from maxapi import Bot
from maxapi.exceptions import InvalidToken, MaxConnection
from maxapi.exceptions import MaxApiError as LibMaxApiError
from maxapi.methods.types.sended_message import SendedMessage

from app.infra.max.throttle import MaxThrottle
from app.infra.max.transport import (
    FakeMaxTransport,
    MaxApiError,
    MaxapiTransport,
    MaxRetryableError,
)
from app.infra.max.types import ButtonCallback, keyboard


async def test_fake_transport_records_send_message() -> None:
    transport = FakeMaxTransport()
    mid = await transport.send_message(chat_id=1, text="hi", format="markdown")
    assert mid.startswith("fake-mid-")
    assert transport.sent_messages[0].chat_id == 1
    assert transport.sent_messages[0].text == "hi"


async def test_fake_transport_records_edit_and_answer() -> None:
    transport = FakeMaxTransport()
    await transport.edit_message("m1", text="new text")
    await transport.answer_callback("cb1", notification="done")
    assert transport.edited_messages[0].message_id == "m1"
    assert transport.answered_callbacks[0].callback_id == "cb1"


async def test_fake_transport_download_configured_result() -> None:
    transport = FakeMaxTransport(download_results={"https://x/y": b"content"})
    data = await transport.download_attachment("https://x/y", max_bytes=100)
    assert data == b"content"
    assert transport.downloads[0].url == "https://x/y"


async def test_fake_transport_injected_failures() -> None:
    transport = FakeMaxTransport(send_message_failures=[MaxApiError(400, "bad", "плохо")])
    with pytest.raises(MaxApiError):
        await transport.send_message(chat_id=1, text="hi")
    assert await transport.send_message(chat_id=1, text="hi")


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.waited: list[float] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.waited.append(delay)
        self.value += delay


class _StubBot(Bot):
    def __init__(self, *, result: Any = None, error: BaseException | None = None) -> None:
        super().__init__(token="test-token", auto_requests=False)
        self._result = result
        self._error = error
        self.calls = 0

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


def _sent(mid: str = "mid-1") -> SendedMessage:
    return SendedMessage.model_validate(
        {
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "timestamp": 1,
                "body": {"mid": mid, "seq": 1, "text": "ok"},
            }
        }
    )


async def test_send_message_returns_mid_and_throttles() -> None:
    clock = _FakeClock()
    transport = MaxapiTransport(
        _StubBot(result=_sent()), throttle=MaxThrottle(per_chat_rps=2.0, clock=clock)
    )

    assert await transport.send_message(chat_id=1, text="раз") == "mid-1"
    await transport.send_message(chat_id=1, text="два")

    assert clock.waited == [pytest.approx(0.5)]


async def test_send_message_requires_single_target() -> None:
    transport = MaxapiTransport(_StubBot(result=_sent()))
    with pytest.raises(ValueError, match="ровно один"):
        await transport.send_message(chat_id=1, user_id=2, text="hi")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LibMaxApiError(code=429, raw={"message": "too many"}), MaxRetryableError),
        (LibMaxApiError(code=503, raw={"message": "later"}), MaxRetryableError),
        (LibMaxApiError(code=400, raw={"message": "bad"}), MaxApiError),
        (MaxConnection("нет связи"), MaxRetryableError),
        (InvalidToken("плохой токен"), MaxApiError),
    ],
)
async def test_library_errors_become_port_errors(
    error: BaseException, expected: type[MaxApiError]
) -> None:
    transport = MaxapiTransport(_StubBot(error=error))
    with pytest.raises(expected) as info:
        await transport.send_message(chat_id=1, text="hi")
    assert "test-token" not in str(info.value)


async def test_empty_response_is_retryable() -> None:
    transport = MaxapiTransport(_StubBot(result=None))
    with pytest.raises(MaxRetryableError):
        await transport.send_message(chat_id=1, text="hi")


def test_keyboard_builds_inline_attachment() -> None:
    attachment = keyboard([[ButtonCallback(text="Принять", payload="a:code")]])
    assert attachment.type == "inline_keyboard"
    assert attachment.payload is not None
    assert attachment.payload.buttons[0][0].text == "Принять"


async def test_download_enforces_size_limit(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://files.test/a").mock(
        return_value=httpx.Response(200, content=b"x" * 100)
    )
    transport = MaxapiTransport(_StubBot())

    assert await transport.download_attachment("https://files.test/a", max_bytes=100) == b"x" * 100
    with pytest.raises(MaxApiError) as info:
        await transport.download_attachment("https://files.test/a", max_bytes=10)
    assert info.value.status == 413


async def test_download_server_error_is_retryable(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://files.test/b").mock(return_value=httpx.Response(503))
    transport = MaxapiTransport(_StubBot())

    with pytest.raises(MaxRetryableError):
        await transport.download_attachment("https://files.test/b", max_bytes=100)


async def test_download_sends_no_bot_token(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://files.test/c").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    transport = MaxapiTransport(_StubBot())

    await transport.download_attachment("https://files.test/c", max_bytes=10)

    assert "authorization" not in {k.lower() for k in route.calls[0].request.headers}


class _CallbackStubBot(Bot):
    def __init__(self) -> None:
        super().__init__(token="test-token", auto_requests=False)
        self.callbacks: list[dict[str, Any]] = []

    async def send_callback(self, *args: Any, **kwargs: Any) -> Any:
        self.callbacks.append(kwargs)
        return None


async def test_empty_callback_answer_is_not_sent() -> None:
    bot = _CallbackStubBot()
    transport = MaxapiTransport(bot)

    await transport.answer_callback("cb-empty")
    await transport.answer_callback("cb-empty", notification="")
    await transport.answer_callback("cb-note", notification="Готово")

    assert [call["callback_id"] for call in bot.callbacks] == ["cb-note"]
