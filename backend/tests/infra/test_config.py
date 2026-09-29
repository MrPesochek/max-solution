import pytest

from app.infra.config import Settings, parse_host_allowlist

BOT = {"max_bot_token": "t", "max_webhook_secret": "s"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV",
        "DEMO_LOGIN_ENABLED",
        "DEMO_LOGIN_WITH_REAL_BOT",
        "MAX_BOT_TOKEN",
        "MAX_UPDATES_MODE",
        "ALLOW_PRIVATE_WEBHOOK_HOSTS",
        "ALLOWED_PRIVATE_WEBHOOK_HOSTS",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("app_env", ["local", "test", "demo"])
@pytest.mark.parametrize("mode", ["webhook", "polling"])
def test_demo_login_with_real_bot_refused_in_any_env(app_env: str, mode: str) -> None:
    with pytest.raises(ValueError, match="DEMO_LOGIN_WITH_REAL_BOT"):
        Settings(app_env=app_env, demo_login_enabled=True, max_updates_mode=mode, **BOT)


def test_demo_login_without_real_bot_allowed() -> None:
    settings = Settings(app_env="local", demo_login_enabled=True)
    assert settings.demo_login_enabled is True
    Settings(app_env="demo", demo_login_enabled=True, max_bot_token="t")


def test_demo_login_with_real_bot_needs_explicit_confirmation() -> None:
    settings = Settings(
        app_env="demo",
        demo_login_enabled=True,
        demo_login_with_real_bot=True,
        max_updates_mode="webhook",
        **BOT,
    )
    assert settings.bot_enabled is True
    assert settings.operator_demo_login_allowed is False


@pytest.mark.parametrize(
    ("app_env", "mode", "allowed"),
    [
        ("local", "off", True),
        ("test", "off", False),
        ("demo", "off", False),
        ("prod", "off", False),
        ("local", "polling", False),
    ],
)
def test_operator_demo_login_only_on_local_without_bot(
    app_env: str, mode: str, allowed: bool
) -> None:
    settings = Settings(app_env=app_env, max_updates_mode=mode, **BOT)
    assert settings.operator_demo_login_allowed is allowed


def test_legacy_global_private_hosts_flag_refused() -> None:
    with pytest.raises(ValueError, match="ALLOWED_PRIVATE_WEBHOOK_HOSTS"):
        Settings(app_env="demo", allow_private_webhook_hosts=True)


def test_private_hosts_allowlist_parsed() -> None:
    settings = Settings(
        app_env="demo", allowed_private_webhook_hosts=" onec-connector:8083, CRM.lan ,[fd00::5]:9"
    )
    assert settings.private_webhook_hosts == {
        ("onec-connector", 8083),
        ("crm.lan", None),
        ("fd00::5", 9),
    }
    assert parse_host_allowlist("") == frozenset()


@pytest.mark.parametrize("raw", ["onec-connector:port", "http://x/y", "host/path", "u@host"])
def test_malformed_allowlist_refused_at_start(raw: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_PRIVATE_WEBHOOK_HOSTS"):
        Settings(app_env="demo", allowed_private_webhook_hosts=raw)


def test_prod_refuses_private_hosts_allowlist() -> None:
    with pytest.raises(ValueError, match="ALLOWED_PRIVATE_WEBHOOK_HOSTS"):
        Settings(app_env="prod", allowed_private_webhook_hosts="onec-connector:8083", **BOT)


def test_prod_requires_https_public_base_url() -> None:
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(app_env="prod", public_base_url="http://repair.example.ru", **BOT)
    Settings(app_env="prod", public_base_url="https://repair.example.ru", **BOT)
    Settings(app_env="prod", public_base_url="http://localhost:8080", **BOT)


def test_previous_webhook_secret_needs_current_one() -> None:
    with pytest.raises(ValueError, match="MAX_WEBHOOK_SECRET_PREVIOUS"):
        Settings(app_env="demo", max_webhook_secret="", max_webhook_secret_previous="old-1")


def test_previous_webhook_secret_must_differ() -> None:
    with pytest.raises(ValueError, match="совпадает"):
        Settings(app_env="demo", max_webhook_secret="same-1", max_webhook_secret_previous="same-1")


def test_previous_webhook_secret_accepted_during_rotation() -> None:
    settings = Settings(
        app_env="demo", max_webhook_secret="new-secret-1", max_webhook_secret_previous="old-1"
    )
    assert settings.max_webhook_secret_previous == "old-1"
    assert (
        settings.max_webhook_rotation_window_seconds > settings.max_webhook_rotation_grace_seconds
    )


def test_webhook_rotation_window_must_be_positive() -> None:
    with pytest.raises(ValueError, match="MAX_WEBHOOK_ROTATION_WINDOW_SECONDS"):
        Settings(app_env="demo", max_webhook_rotation_window_seconds=0)
