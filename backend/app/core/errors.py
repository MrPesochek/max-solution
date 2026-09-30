from typing import Any


class DomainError(Exception):
    status = 400
    code = "BAD_REQUEST"
    default_message = "Некорректный запрос"

    def __init__(self, message: str | None = None, *, code: str | None = None, **details: Any):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        if code:
            self.code = code
        self.details: dict[str, Any] = details


class Unauthenticated(DomainError):
    status = 401
    code = "UNAUTHENTICATED"
    default_message = "Требуется вход"


class Forbidden(DomainError):
    status = 403
    code = "FORBIDDEN"
    default_message = "Недостаточно прав"


class NotFound(DomainError):
    status = 404
    code = "NOT_FOUND"
    default_message = "Объект не найден"


class Conflict(DomainError):
    status = 409
    code = "CONFLICT"
    default_message = "Конфликт состояния"


class VersionConflict(Conflict):
    code = "VERSION_CONFLICT"
    default_message = "Данные изменились"

    def __init__(self, current_version: int, message: str | None = None):
        super().__init__(message, current_version=current_version)


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"
    default_message = "Действие недоступно в текущем состоянии"


class IdempotencyConflict(Conflict):
    code = "IDEMPOTENCY_CONFLICT"
    default_message = "Ключ идемпотентности уже использован с другим запросом"


class ValidationFailed(DomainError):
    status = 422
    code = "VALIDATION_FAILED"
    default_message = "Ошибка проверки полей"


class RateLimited(DomainError):
    status = 429
    code = "RATE_LIMITED"
    default_message = "Слишком много запросов"
