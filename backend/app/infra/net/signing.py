from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def sign_webhook(secret: bytes, timestamp: int, raw_body: bytes) -> str:
    mac = hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{mac}"


def verify_webhook_signature(
    secret: bytes,
    timestamp: int,
    raw_body: bytes,
    signature: str,
    *,
    max_age_seconds: int,
    now: int,
) -> bool:
    if abs(now - timestamp) > max_age_seconds:
        return False
    expected = sign_webhook(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature)
