from collections.abc import Iterator

import pytest

from app.infra.config import Settings
from app.infra.max.types import ButtonCallback, ButtonOpenApp, open_webapp_button, webapp_button
from tests.factories import BOT_USERNAME, apply_test_settings


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from apply_test_settings(monkeypatch)


@pytest.fixture
def without_username(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from apply_test_settings(
        monkeypatch, MAX_BOT_USERNAME="", PUBLIC_BASE_URL="https://app.test"
    )


def test_open_app_button_carries_screen_and_object(configured: Settings) -> None:
    button = webapp_button("Открыть", "request", "req_0000000000000000000001")
    assert isinstance(button, ButtonOpenApp)
    assert button.web_app == BOT_USERNAME
    assert button.payload == "req_req_0000000000000000000001"


def test_open_app_button_without_object(configured: Settings) -> None:
    button = webapp_button("Открыть", "organization")
    assert isinstance(button, ButtonOpenApp)
    assert button.payload == "scr_organization"


def test_url_alias_fills_web_app(configured: Settings) -> None:
    button = ButtonOpenApp(text="Открыть", url="https://max.ru/repairbot")
    assert button.web_app == "https://max.ru/repairbot"


def test_falls_back_to_link_without_bot_username(without_username: Settings) -> None:
    attachment = open_webapp_button("request", "req_1")
    button = attachment.payload.buttons[0][0]  # type: ignore[union-attr]
    assert button.type == "link"
    assert button.url == "https://app.test/?screen=request&id=req_1"


@pytest.fixture
def link_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from apply_test_settings(monkeypatch, MAX_WEBAPP_MODE="link")


def test_link_mode_button_is_callback_without_token(link_mode: Settings) -> None:
    button = webapp_button("Открыть", "request", "req_0000000000000000000001")
    assert isinstance(button, ButtonCallback)
    assert button.payload == "o:req_req_0000000000000000000001"


def test_link_mode_payload_fits_max_limit(link_mode: Settings) -> None:
    button = webapp_button("Открыть", "available", "req_0000000000000000000001")
    assert isinstance(button, ButtonCallback)
    assert button.payload == "o:mkt_req_0000000000000000000001"
    assert len(button.payload) <= 128
