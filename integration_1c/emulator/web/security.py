from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionPayload:
    issued_at: int
    expires_at: int


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_session_cookie(secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {"issued_at": now, "expires_at": now + ttl_seconds}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_session_cookie(secret: str, cookie_value: str | None) -> bool:
    if not cookie_value or "." not in cookie_value:
        return False
    body, _, signature = cookie_value.rpartition(".")
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, UnicodeDecodeError):
        return False
    expires_at = payload.get("expires_at")
    return isinstance(expires_at, int) and expires_at >= int(time.time())


def check_password(configured: str, provided: str) -> bool:
    return hmac.compare_digest(configured.encode("utf-8"), provided.encode("utf-8"))


def csrf_token(secret: str, nonce: str) -> str:
    """Токен формы для double-submit: HMAC от случайного значения из cookie."""
    return hmac.new(secret.encode(), f"csrf.{nonce}".encode(), hashlib.sha256).hexdigest()
