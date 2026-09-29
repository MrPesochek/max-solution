import pytest

from app.infra.max.deeplinks import (
    BOT_START_PARAM_LIMIT,
    WEBAPP_START_PARAM_LIMIT,
    DeeplinkError,
    bot_start_link,
    build_start_param,
    parse_start_param,
    webapp_start_link,
)


def test_build_and_parse_start_param_roundtrip() -> None:
    param = build_start_param("invite", "abcDEF123-_")
    assert param == "invite_abcDEF123-_"
    kind, value = parse_start_param(param)
    assert kind == "invite"
    assert value == "abcDEF123-_"


def test_build_start_param_rejects_forbidden_chars() -> None:
    with pytest.raises(DeeplinkError):
        build_start_param("invite", "значение")


def test_bot_start_link_limit() -> None:
    payload = "a" * BOT_START_PARAM_LIMIT
    link = bot_start_link("repair_bot", payload)
    assert link == f"https://max.ru/repair_bot?start={payload}"

    with pytest.raises(DeeplinkError):
        bot_start_link("repair_bot", "a" * (BOT_START_PARAM_LIMIT + 1))


def test_webapp_start_link_limit() -> None:
    payload = "a" * WEBAPP_START_PARAM_LIMIT
    link = webapp_start_link("repair_bot", payload)
    assert link == f"https://max.ru/repair_bot?startapp={payload}"

    with pytest.raises(DeeplinkError):
        webapp_start_link("repair_bot", "a" * (WEBAPP_START_PARAM_LIMIT + 1))


def test_custom_base_url() -> None:
    link = bot_start_link("repair_bot", "abc", base_url="https://staging.max.example")
    assert link == "https://staging.max.example/repair_bot?start=abc"


def test_parse_start_param_malformed() -> None:
    with pytest.raises(DeeplinkError):
        parse_start_param("noundersore")
    with pytest.raises(DeeplinkError):
        parse_start_param("_novalue")
