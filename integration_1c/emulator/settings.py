from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_PASSWORD = "demo"
_DEFAULT_SESSION_SECRET = "change-me-session-secret"
_DEFAULT_ODATA_PASSWORD = "odata-demo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONEC_EMULATOR_", env_file=".env", extra="ignore")

    base_name: str = "unf_demo"
    odata_username: str = "odata"
    odata_password: str = _DEFAULT_ODATA_PASSWORD

    ui_password: str = _DEFAULT_PASSWORD
    session_secret: str = _DEFAULT_SESSION_SECRET
    session_ttl_seconds: int = 12 * 3600
    allow_defaults: bool = False
    login_max_failures: int = 5
    login_failure_window_seconds: int = 300

    database_path: str = "./data/onec_emulator.sqlite3"
    max_body_bytes: int = 20 * 1024 * 1024

    @model_validator(mode="after")
    def _refuse_defaults(self) -> Settings:
        if self.allow_defaults:
            return self
        for value, default, name in (
            (self.ui_password, _DEFAULT_PASSWORD, "UI_PASSWORD"),
            (self.session_secret, _DEFAULT_SESSION_SECRET, "SESSION_SECRET"),
            (self.odata_password, _DEFAULT_ODATA_PASSWORD, "ODATA_PASSWORD"),
        ):
            if value == default:
                raise ValueError(
                    f"ONEC_EMULATOR_{name} не задан (значение по умолчанию); "
                    "для локального стенда — ONEC_EMULATOR_ALLOW_DEFAULTS=true"
                )
        return self

    def database_file(self) -> Path:
        return Path(self.database_path)


def get_settings() -> Settings:
    return Settings()
