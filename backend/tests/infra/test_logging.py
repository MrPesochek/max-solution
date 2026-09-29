import json

import structlog

from app.infra.logging import configure_logging, mask_sensitive


def test_mask_sensitive_top_level_keys() -> None:
    event = {
        "event": "webhook_sent",
        "authorization": "Bearer abc",
        "token": "xyz",
        "secret": "s3cr3t",
        "init_data": "user=...&hash=...",
        "phone": "+79990000000",
        "text": "текст сообщения",
        "body": b"raw body",
        "status": 200,
    }
    masked = mask_sensitive(None, "info", event)
    assert masked["authorization"] == "***"
    assert masked["token"] == "***"
    assert masked["secret"] == "***"
    assert masked["init_data"] == "***"
    assert masked["phone"] == "***"
    assert masked["text"] == "***"
    assert masked["body"] == "***"
    assert masked["status"] == 200
    assert masked["event"] == "webhook_sent"


def test_mask_sensitive_nested_dict_and_list() -> None:
    event = {
        "request": {
            "headers": {"Authorization": "Bearer abc", "X-Trace": "1"},
            "items": [{"phone": "+7999"}, {"note": "ok"}],
        }
    }
    masked = mask_sensitive(None, "info", event)
    assert masked["request"]["headers"]["Authorization"] == "***"
    assert masked["request"]["headers"]["X-Trace"] == "1"
    assert masked["request"]["items"][0]["phone"] == "***"
    assert masked["request"]["items"][1]["note"] == "ok"


def test_key_matching_is_case_and_substring_insensitive() -> None:
    event = {"Access_Token": "abc", "user_secret_key": "xyz", "normal_field": "value"}
    masked = mask_sensitive(None, "info", event)
    assert masked["Access_Token"] == "***"
    assert masked["user_secret_key"] == "***"
    assert masked["normal_field"] == "value"


def test_configure_logging_emits_json_with_masking_and_request_id(capsys) -> None:
    configure_logging("prod")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-1")
    try:
        logger = structlog.get_logger()
        logger.info("token_used", token="super-secret", ok=True)
    finally:
        structlog.contextvars.clear_contextvars()

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["token"] == "***"
    assert payload["ok"] is True
    assert payload["request_id"] == "req-1"
    assert payload["event"] == "token_used"
