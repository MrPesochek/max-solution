from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import quote, urlencode

BOT_START_PARAM_LIMIT = 128
WEBAPP_START_PARAM_LIMIT = 512
DEFAULT_BASE_URL = "https://max.ru"

_ALPHABET_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DeeplinkKind(StrEnum):
    BOT = "bot"
    WEBAPP = "webapp"


class DeeplinkError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _validate_alphabet(payload: str) -> None:
    if not payload or not _ALPHABET_RE.match(payload):
        raise DeeplinkError("invalid_alphabet")


def build_start_param(kind: str, value: str) -> str:
    if not kind or not value:
        raise DeeplinkError("empty_part")
    for part in (kind, value):
        _validate_alphabet(part)
    return f"{kind}_{value}"


def parse_start_param(param: str) -> tuple[str, str]:
    _validate_alphabet(param)
    kind, sep, value = param.partition("_")
    if not sep or not kind or not value:
        raise DeeplinkError("malformed_param")
    return kind, value


def bot_start_link(bot_username: str, payload: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    _validate_alphabet(payload)
    if len(payload) > BOT_START_PARAM_LIMIT:
        raise DeeplinkError("payload_too_long")
    query = urlencode({"start": payload})
    return f"{base_url}/{quote(bot_username)}?{query}"


def webapp_start_link(bot_username: str, payload: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    _validate_alphabet(payload)
    if len(payload) > WEBAPP_START_PARAM_LIMIT:
        raise DeeplinkError("payload_too_long")
    query = urlencode({"startapp": payload})
    return f"{base_url}/{quote(bot_username)}?{query}"


_OBJECT_TARGET_KINDS = {"request": "req", "available": "mkt"}
SCREEN_TARGET_KIND = "scr"


def webapp_target(screen: str, object_public_id: str | None = None) -> str | None:
    try:
        kind = _OBJECT_TARGET_KINDS.get(screen)
        if kind is not None and object_public_id is not None:
            return build_start_param(kind, object_public_id)
        return build_start_param(SCREEN_TARGET_KIND, screen)
    except DeeplinkError:
        return None


def is_webapp_target(value: str) -> bool:
    return len(value) <= WEBAPP_START_PARAM_LIMIT and bool(_ALPHABET_RE.match(value))
