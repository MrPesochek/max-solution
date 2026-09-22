from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import parse_qsl

from pydantic import BaseModel, ConfigDict, ValidationError

_SECRET_KEY_MESSAGE = b"WebAppData"


class InitDataErrorReason(StrEnum):
    DUPLICATE_PARAM = "duplicate_param"
    MISSING_HASH = "missing_hash"
    MISSING_AUTH_DATE = "missing_auth_date"
    MISSING_USER = "missing_user"
    INVALID_AUTH_DATE = "invalid_auth_date"
    INVALID_USER_JSON = "invalid_user_json"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"
    FUTURE_AUTH_DATE = "future_auth_date"


class InitDataError(Exception):
    def __init__(self, reason: InitDataErrorReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class _InitDataUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


class InitData(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    start_param: str | None
    auth_date: datetime
    query_id: str | None
    signature: str


def _data_check_string(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(pairs, key=lambda kv: kv[0]))


def validate_init_data(
    raw: str,
    bot_token: str,
    *,
    max_age: int,
    clock_skew: int,
    now: datetime,
) -> InitData:
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=False)

    seen_keys: set[str] = set()
    values: dict[str, str] = {}
    for key, value in pairs:
        if key in seen_keys:
            raise InitDataError(InitDataErrorReason.DUPLICATE_PARAM)
        seen_keys.add(key)
        values[key] = value

    received_hash = values.pop("hash", None)
    if not received_hash:
        raise InitDataError(InitDataErrorReason.MISSING_HASH)

    auth_date_raw = values.get("auth_date")
    if not auth_date_raw:
        raise InitDataError(InitDataErrorReason.MISSING_AUTH_DATE)

    user_raw = values.get("user")
    if not user_raw:
        raise InitDataError(InitDataErrorReason.MISSING_USER)

    check_string = _data_check_string(list(values.items()))
    secret_key = hmac.new(_SECRET_KEY_MESSAGE, bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError(InitDataErrorReason.BAD_SIGNATURE)

    try:
        auth_date_ts = int(auth_date_raw)
    except ValueError as exc:
        raise InitDataError(InitDataErrorReason.INVALID_AUTH_DATE) from exc
    auth_date = datetime.fromtimestamp(auth_date_ts, tz=UTC)

    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_seconds = (now - auth_date).total_seconds()
    if age_seconds > max_age + clock_skew:
        raise InitDataError(InitDataErrorReason.EXPIRED)
    if age_seconds < -clock_skew:
        raise InitDataError(InitDataErrorReason.FUTURE_AUTH_DATE)

    try:
        user_dict = json.loads(user_raw)
        user = _InitDataUser.model_validate(user_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InitDataError(InitDataErrorReason.INVALID_USER_JSON) from exc

    return InitData(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        start_param=values.get("start_param"),
        auth_date=auth_date,
        query_id=values.get("query_id"),
        signature=expected_hash,
    )
