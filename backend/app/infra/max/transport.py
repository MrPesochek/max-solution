from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import httpx
from aiohttp import ClientError
from maxapi.exceptions import (
    DownloadFileError,
    InvalidToken,
    MaxConnection,
    MaxError,
)
from maxapi.exceptions import MaxApiError as LibMaxApiError
from maxapi.types.attachments import Attachment, AttachmentUpload
from maxapi.types.input_media import InputMedia, InputMediaBuffer

from app.infra.max.throttle import MaxThrottle
from app.infra.max.types import NewMessageBody, OutgoingAttachment, TextFormat

if TYPE_CHECKING:
    from maxapi import Bot


class MaxApiError(Exception):
    """Ошибка ответа MAX Bot API. Никогда не включает токен бота."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"MAX API error {status} {code}: {message}")


class MaxRetryableError(MaxApiError):
    """429/5xx и сетевые сбои — вызывающий код может повторить запрос."""

    def __init__(
        self, status: int, code: str, message: str, retry_after: float | None = None
    ) -> None:
        super().__init__(status, code, message)
        self.retry_after = retry_after


class MaxTransport(Protocol):
    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> str:
        """Отправляет сообщение и возвращает mid отправленного сообщения."""
        ...

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> None: ...

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: NewMessageBody | None = None,
        notification: str | None = None,
    ) -> None: ...

    async def download_attachment(self, url: str, *, max_bytes: int) -> bytes: ...


def _translate(exc: BaseException) -> MaxApiError:
    """Ошибка библиотеки или сети → ошибка порта."""
    if isinstance(exc, InvalidToken):
        return MaxApiError(401, "invalid_token", "Токен бота отклонён MAX")
    if isinstance(exc, LibMaxApiError):
        raw = exc.raw
        message = str(raw.get("message") or raw) if isinstance(raw, dict) else str(raw)
        code = str(raw.get("code") or "max_api_error") if isinstance(raw, dict) else "max_api_error"
        if exc.code == 429 or exc.code >= 500:
            return MaxRetryableError(exc.code, code, message)
        return MaxApiError(exc.code, code, message)
    if isinstance(exc, MaxConnection | DownloadFileError | ClientError | TimeoutError):
        return MaxRetryableError(503, "connection_error", "Нет связи с MAX")
    if isinstance(exc, MaxError):
        return MaxApiError(502, "max_error", "Ошибка клиента MAX")
    return MaxApiError(502, "max_error", "Ошибка клиента MAX")


class MaxapiTransport:
    """Реализация порта поверх `maxapi.Bot` с ограничителем частоты.

    Скачивание вложений идёт отдельным HTTP-клиентом без заголовка авторизации:
    ссылка вложения ведёт на файловый хост MAX, и токен бота туда не отправляется.
    """

    def __init__(
        self,
        bot: Bot,
        *,
        throttle: MaxThrottle | None = None,
        download_timeout: float = 30.0,
    ) -> None:
        self._bot = bot
        self._throttle = throttle or MaxThrottle()
        self._download_timeout = download_timeout

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> str:
        if (user_id is None) == (chat_id is None):
            raise ValueError("нужно указать ровно один из user_id или chat_id")
        await self._throttle.acquire(chat_id if chat_id is not None else int(user_id or 0))
        try:
            sent = await self._bot.send_message(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                format=format,
                attachments=_payload(attachments),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        body = sent.message.body if sent is not None else None
        if body is None or not body.mid:
            raise MaxRetryableError(502, "empty_response", "MAX не вернул отправленное сообщение")
        return body.mid

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> None:
        await self._throttle.acquire(_bucket(message_id))
        try:
            await self._bot.edit_message(
                message_id=message_id,
                text=text,
                format=format,
                attachments=_payload(attachments),
            )
        except Exception as exc:
            raise _translate(exc) from exc

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: NewMessageBody | None = None,
        notification: str | None = None,
    ) -> None:
        if message is None and not notification:
            return
        await self._throttle.acquire(_bucket(callback_id))
        try:
            await self._bot.send_callback(
                callback_id=callback_id, message=message, notification=notification
            )
        except Exception as exc:
            raise _translate(exc) from exc

    async def download_attachment(self, url: str, *, max_bytes: int) -> bytes:
        try:
            async with (
                httpx.AsyncClient(timeout=self._download_timeout, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code == 429 or response.status_code >= 500:
                    raise MaxRetryableError(
                        response.status_code, "download_failed", "Не удалось скачать вложение"
                    )
                if response.status_code >= 400:
                    raise MaxApiError(
                        response.status_code, "download_failed", "Не удалось скачать вложение"
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise MaxApiError(413, "attachment_too_large", "Вложение слишком большое")
                    chunks.append(chunk)
        except MaxApiError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MaxRetryableError(503, "connection_error", "Нет связи с MAX") from exc
        except Exception as exc:
            raise _translate(exc) from exc
        return b"".join(chunks)

    async def aclose(self) -> None:
        await self._bot.close_session()


def _bucket(key: str) -> int:
    return zlib.crc32(key.encode("utf-8"))


def _payload(
    attachments: list[OutgoingAttachment] | None,
) -> list[Attachment | InputMedia | InputMediaBuffer | AttachmentUpload] | None:
    return list(attachments) if attachments else None


@dataclass
class SentMessageCall:
    user_id: int | None
    chat_id: int | None
    text: str | None
    format: TextFormat | None
    attachments: list[OutgoingAttachment] | None


@dataclass
class EditMessageCall:
    message_id: str
    text: str | None
    format: TextFormat | None
    attachments: list[OutgoingAttachment] | None


@dataclass
class AnswerCallbackCall:
    callback_id: str
    message: NewMessageBody | None
    notification: str | None


@dataclass
class DownloadCall:
    url: str
    max_bytes: int


@dataclass
class FakeMaxTransport:
    """Реализация MaxTransport для юнит-тестов. Записывает вызовы, не ходит в сеть.

    Сбои задаются очередями исключений: следующий вызов метода вместо результата
    поднимает исключение из соответствующей очереди (если она не пуста).
    """

    sent_messages: list[SentMessageCall] = field(default_factory=list)
    edited_messages: list[EditMessageCall] = field(default_factory=list)
    answered_callbacks: list[AnswerCallbackCall] = field(default_factory=list)
    downloads: list[DownloadCall] = field(default_factory=list)

    download_results: dict[str, bytes] = field(default_factory=dict)
    default_download_result: bytes = b""

    send_message_failures: list[BaseException] = field(default_factory=list)
    edit_message_failures: list[BaseException] = field(default_factory=list)
    answer_callback_failures: list[BaseException] = field(default_factory=list)
    download_failures: list[BaseException] = field(default_factory=list)

    _next_mid: int = 0

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> str:
        self.sent_messages.append(SentMessageCall(user_id, chat_id, text, format, attachments))
        if self.send_message_failures:
            raise self.send_message_failures.pop(0)
        self._next_mid += 1
        return f"fake-mid-{self._next_mid}"

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> None:
        self.edited_messages.append(EditMessageCall(message_id, text, format, attachments))
        if self.edit_message_failures:
            raise self.edit_message_failures.pop(0)

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: NewMessageBody | None = None,
        notification: str | None = None,
    ) -> None:
        self.answered_callbacks.append(AnswerCallbackCall(callback_id, message, notification))
        if self.answer_callback_failures:
            raise self.answer_callback_failures.pop(0)

    async def download_attachment(self, url: str, *, max_bytes: int) -> bytes:
        self.downloads.append(DownloadCall(url, max_bytes))
        if self.download_failures:
            raise self.download_failures.pop(0)
        return self.download_results.get(url, self.default_download_result)
