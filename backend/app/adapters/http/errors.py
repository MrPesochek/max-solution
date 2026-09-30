import json
import uuid
from typing import Any

import asyncpg
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.ids import InvalidPublicId

log = structlog.get_logger(__name__)


class ErrorBody(BaseModel):
    code: str = Field(description="Машиночитаемый код ошибки, например NOT_FOUND.")
    message: str = Field(description="Сообщение на русском для лога/UI.")
    request_id: str = Field(
        description="Идентификатор запроса — тот же, что в заголовке X-Request-ID."
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Дополнительные поля ошибки, зависят от кода."
    )


class ErrorResponse(BaseModel):
    error: ErrorBody


STANDARD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Некорректный запрос."},
    401: {"model": ErrorResponse, "description": "Не пройдена аутентификация."},
    403: {"model": ErrorResponse, "description": "Недостаточно прав или scope."},
    404: {"model": ErrorResponse, "description": "Объект не найден или недоступен вызывающему."},
    409: {
        "model": ErrorResponse,
        "description": "Конфликт состояния: версия, идемпотентность или недопустимый переход.",
    },
    422: {"model": ErrorResponse, "description": "Ошибка проверки полей."},
    429: {"model": ErrorResponse, "description": "Слишком много запросов."},
    503: {"model": ErrorResponse, "description": "Сервис временно недоступен, повторите позже."},
}

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = request.state.request_id = uuid.uuid4().hex
    return str(rid)


def error_response(
    request: Request, status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_of(request),
            "details": details or {},
        }
    }
    return JSONResponse(body, status_code=status, headers={"X-Request-ID": request_id_of(request)})


_MALFORMED_BODY_ERRORS = frozenset({"json_invalid", "json_type"})

_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.TooManyConnectionsError,
    ConnectionError,
)
UNAVAILABLE_RETRY_AFTER = 5


def error_body(request_id: str, code: str, message: str) -> bytes:
    body = {"error": {"code": code, "message": message, "request_id": request_id, "details": {}}}
    return json.dumps(body, ensure_ascii=False).encode()


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(InvalidPublicId)
    async def _bad_id(request: Request, exc: InvalidPublicId) -> JSONResponse:
        return error_response(request, 404, "NOT_FOUND", "Объект не найден")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if any(e["type"] in _MALFORMED_BODY_ERRORS and e["loc"][:1] == ("body",) for e in errors):
            return error_response(request, 400, "BAD_REQUEST", "Тело запроса не является JSON")
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["type"]} for e in errors
        ]
        return error_response(
            request, 422, "VALIDATION_FAILED", "Ошибка проверки полей", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))

    async def _unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.error("service_unavailable", path=request.url.path, error=type(exc).__name__)
        response = error_response(
            request, 503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен, повторите позже"
        )
        response.headers["Retry-After"] = str(UNAVAILABLE_RETRY_AFTER)
        return response

    for error_type in _UNAVAILABLE_ERRORS:
        app.add_exception_handler(error_type, _unavailable)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return error_response(request, 500, "INTERNAL_ERROR", "Внутренняя ошибка")
