from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.adapters.http.errors import error_body
from app.infra.config import get_settings

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
_MESSAGE = "Слишком большое тело запроса"


class BodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail=_MESSAGE)


def body_limit_for(scope: Scope) -> int:
    settings = get_settings()
    content_type = _header(scope, b"content-type") or b""
    if content_type.lower().startswith(b"multipart/"):
        return settings.max_upload_request_bytes
    return settings.max_request_body_bytes


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value)
    return None


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = body_limit_for(scope)
        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(scope, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await _reject(scope, send)


async def _reject(scope: Scope, send: Send) -> None:
    request_id = str(scope.get("state", {}).get("request_id", ""))
    payload = error_body(request_id, "PAYLOAD_TOO_LARGE", _MESSAGE)
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
        (b"connection", b"close"),
    ]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
