from __future__ import annotations

import hashlib
import hmac
import time

_SIGNATURE_PREFIX = "sha256="


def sign_webhook(secret: str, timestamp: int, raw_body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{mac}"


def verify_webhook_signature(
    secret: str,
    timestamp: int,
    raw_body: bytes,
    signature: str,
    *,
    max_age_seconds: int,
    now: int | None = None,
) -> bool:
    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > max_age_seconds:
        return False
    if not signature.startswith(_SIGNATURE_PREFIX):
        return False
    expected = sign_webhook(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature)
