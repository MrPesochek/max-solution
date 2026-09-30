import structlog
from maxapi import Bot

from app.infra.config import get_settings
from app.infra.max.throttle import MaxThrottle
from app.infra.max.transport import MaxapiTransport, MaxTransport
from app.infra.max.types import NewMessageBody, OutgoingAttachment, TextFormat

log = structlog.get_logger("worker.max")

_transport: MaxTransport | None = None


class LoggingMaxTransport:
    def __init__(self) -> None:
        self._counter = 0

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> str:
        self._counter += 1
        log.info("max_send_stub", has_attachments=bool(attachments))
        return f"stub-mid-{self._counter}"

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> None:
        log.info("max_edit_stub")

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: NewMessageBody | None = None,
        notification: str | None = None,
    ) -> None:
        log.info("max_answer_stub")

    async def download_attachment(self, url: str, *, max_bytes: int) -> bytes:
        log.info("max_download_stub")
        return b""


def get_max_transport() -> MaxTransport:
    global _transport
    if _transport is None:
        _transport = _build()
    return _transport


def set_max_transport(transport: MaxTransport | None) -> None:
    global _transport
    _transport = transport


def _build() -> MaxTransport:
    settings = get_settings()
    if settings.max_updates_mode == "off" or not settings.max_bot_token:
        log.warning(
            "max_transport_stub",
            reason="no_token" if not settings.max_bot_token else "mode_off",
        )
        return LoggingMaxTransport()
    bot = Bot(token=settings.max_bot_token, auto_requests=False)
    bot.set_api_url(settings.max_api_base_url)
    return MaxapiTransport(
        bot,
        throttle=MaxThrottle(
            per_chat_rps=settings.max_per_chat_rps, global_rps=settings.max_global_rps
        ),
    )
