import hashlib
import hmac
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from app.infra.max.init_data import InitDataError, InitDataErrorReason, validate_init_data

BOT_TOKEN = "123456:test-bot-token"
AUTH_DATE = 1_700_000_000
NOW = datetime.fromtimestamp(AUTH_DATE + 10, tz=UTC)


def _build_raw(fields: dict[str, str], *, token: str = BOT_TOKEN) -> str:
    """Собирает валидную строку initData тем же алгоритмом, что и validate_init_data."""
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    all_fields = {**fields, "hash": signature}
    return urlencode(all_fields)


def _base_fields() -> dict[str, str]:
    user = {"id": 42, "first_name": "Иван", "username": "ivan"}
    return {
        "auth_date": str(AUTH_DATE),
        "user": json.dumps(user, ensure_ascii=False),
        "query_id": "q1",
        "start_param": "invite_abc",
    }


def test_valid_reference_vector() -> None:
    raw = _build_raw(_base_fields())
    result = validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert result.user_id == 42
    assert result.first_name == "Иван"
    assert result.username == "ivan"
    assert result.start_param == "invite_abc"
    assert result.query_id == "q1"
    assert result.auth_date == datetime.fromtimestamp(AUTH_DATE, tz=UTC)


def test_missing_hash() -> None:
    fields = _base_fields()
    raw = urlencode(fields)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.MISSING_HASH


def test_duplicate_param() -> None:
    raw = _build_raw(_base_fields()) + "&auth_date=" + str(AUTH_DATE)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.DUPLICATE_PARAM


def test_missing_auth_date() -> None:
    fields = _base_fields()
    del fields["auth_date"]
    raw = _build_raw(fields)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.MISSING_AUTH_DATE


def test_missing_user() -> None:
    fields = _base_fields()
    del fields["user"]
    raw = _build_raw(fields)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.MISSING_USER


def test_invalid_auth_date_value() -> None:
    fields = _base_fields()
    fields["auth_date"] = "not-a-number"
    raw = _build_raw(fields)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.INVALID_AUTH_DATE


def test_expired() -> None:
    raw = _build_raw(_base_fields())
    too_late = datetime.fromtimestamp(AUTH_DATE + 3600, tz=UTC)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=too_late)
    assert exc_info.value.reason == InitDataErrorReason.EXPIRED


def test_future_auth_date() -> None:
    raw = _build_raw(_base_fields())
    too_early = datetime.fromtimestamp(AUTH_DATE - 3600, tz=UTC)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=too_early)
    assert exc_info.value.reason == InitDataErrorReason.FUTURE_AUTH_DATE


def test_invalid_user_json() -> None:
    fields = _base_fields()
    fields["user"] = "not-json"
    raw = _build_raw(fields)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.INVALID_USER_JSON


@pytest.mark.parametrize("field_to_tamper", ["auth_date", "user", "query_id", "start_param"])
def test_tampering_any_field_breaks_signature(field_to_tamper: str) -> None:
    fields = _base_fields()
    raw = _build_raw(fields)
    from urllib.parse import parse_qsl

    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    pairs[field_to_tamper] = pairs[field_to_tamper] + "_tampered"
    tampered_raw = urlencode(pairs)
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(tampered_raw, BOT_TOKEN, max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.BAD_SIGNATURE


def test_wrong_bot_token_breaks_signature() -> None:
    raw = _build_raw(_base_fields())
    with pytest.raises(InitDataError) as exc_info:
        validate_init_data(raw, "другой-токен", max_age=300, clock_skew=60, now=NOW)
    assert exc_info.value.reason == InitDataErrorReason.BAD_SIGNATURE
