from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


def hash_token(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def token_prefix(raw: str) -> str:
    """Несекретная метка токена для журналов и интерфейса: начало хеша, не самого токена."""
    return hash_token(raw).hex()[:8]


def generate_token(nbytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    left = a.encode("utf-8") if isinstance(a, str) else a
    right = b.encode("utf-8") if isinstance(b, str) else b
    return hmac.compare_digest(left, right)


class SecretBoxError(Exception):
    pass


class SecretBox:
    """Симметричное шифрование секретов (например, секретов подписки вебхуков)
    ключами из настроек (`secrets_encryption_key`) — Fernet, base64url 32 байта.

    Ключей может быть несколько через запятую (ротация): шифрует первый,
    расшифровывает любой. `rotate` перешифровывает токен первым ключом.
    """

    def __init__(self, key: str | None) -> None:
        keys = [part.strip() for part in (key or "").split(",") if part.strip()]
        if not keys:
            raise SecretBoxError("ключ шифрования не задан (secrets_encryption_key)")
        try:
            self._fernet = MultiFernet([Fernet(k.encode("ascii")) for k in keys])
        except (ValueError, TypeError) as exc:
            raise SecretBoxError(
                "неверный формат ключа шифрования: ожидается Fernet-ключ (32 байта в base64url)"
            ) from exc

    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise SecretBoxError("не удалось расшифровать данные: неверный ключ или токен") from exc

    def rotate(self, token: bytes) -> bytes:
        try:
            return self._fernet.rotate(token)
        except InvalidToken as exc:
            raise SecretBoxError("не удалось расшифровать данные: неверный ключ или токен") from exc
