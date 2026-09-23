from typing import Annotated, Any

from fastapi import Header

from app.core.errors import ValidationFailed
from app.core.pipeline import Idempotency, hash_body


def idempotency_key_header(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if not idempotency_key or not (8 <= len(idempotency_key) <= 128):
        raise ValidationFailed(
            "Нужен заголовок Idempotency-Key длиной 8–128 символов", field="Idempotency-Key"
        )
    return idempotency_key


IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key")]


def make_idempotency(key: str, operation: str, payload: Any) -> Idempotency:
    return Idempotency(key=key, operation=operation, body_hash=hash_body(payload))
