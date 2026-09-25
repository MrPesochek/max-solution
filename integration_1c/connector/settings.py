from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
_LOCAL_PLATFORM_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "api"})


class Settings(BaseSettings):
    """Настройки коннектора 1С. Всё — из окружения, секретов в коде нет (ТЗ 12)."""

    model_config = SettingsConfigDict(env_prefix="CONNECTOR_", env_file=".env", extra="ignore")

    platform_api_base_url: str = "http://localhost:8000/api/v1"
    platform_api_key: str = ""
    platform_allow_http: bool = False
    public_base_url: str = "http://localhost:8083"

    onec_odata_url: str = "https://localhost/unf/odata/standard.odata"
    onec_username: str = ""
    onec_password: str = ""
    onec_verify_tls: str = "true"
    onec_timeout_seconds: float = 30.0
    onec_allow_http: bool = False

    profile: str = "unf"

    poll_interval_seconds: float = 15.0
    poll_batch_size: int = 20
    action_max_attempts: int = 5

    database_path: str = "./data/connector.sqlite3"
    attachment_max_bytes: int = 10 * 1024 * 1024

    webhook_signature_max_age_seconds: int = 300
    background_retry_attempts: int = 6
    background_retry_base_delay_seconds: float = 1.0
    event_retry_max_rounds: int = 12
    event_retry_base_delay_seconds: float = 60.0
    event_retry_max_delay_seconds: float = 3600.0
    http_timeout_seconds: float = 10.0
    bootstrap_retry_seconds: float = 15.0
    recovery_interval_seconds: float = 60.0

    @model_validator(mode="after")
    def _require_tls_for_basic(self) -> Settings:
        scheme = urlsplit(self.onec_odata_url).scheme
        if scheme not in {"http", "https"}:
            raise ValueError("CONNECTOR_ONEC_ODATA_URL должен начинаться с https://")
        if scheme == "http" and not self.onec_allow_http:
            raise ValueError(
                "Basic-аутентификация 1С по http запрещена: укажите https:// "
                "(для эмулятора в сети стенда — CONNECTOR_ONEC_ALLOW_HTTP=true)"
            )
        return self

    @model_validator(mode="after")
    def _require_tls_for_platform(self) -> Settings:
        parts = urlsplit(self.platform_api_base_url)
        if parts.scheme not in {"http", "https"}:
            raise ValueError("CONNECTOR_PLATFORM_API_BASE_URL должен начинаться с https://")
        if (
            parts.scheme == "http"
            and parts.hostname not in _LOCAL_PLATFORM_HOSTS
            and not self.platform_allow_http
        ):
            raise ValueError(
                "ключ платформы по http уйдёт открытым текстом: укажите https:// в "
                "CONNECTOR_PLATFORM_API_BASE_URL (для закрытой сети стенда — "
                "CONNECTOR_PLATFORM_ALLOW_HTTP=true)"
            )
        return self

    def verify_tls(self) -> bool | str:
        value = self.onec_verify_tls.strip()
        if value.lower() in {"", "true", "1", "yes"}:
            return True
        if value.lower() in {"false", "0", "no"}:
            return False
        return value

    def profile_path(self) -> Path:
        candidate = Path(self.profile)
        if candidate.suffix in {".yaml", ".yml"}:
            return candidate
        return PROFILES_DIR / f"{self.profile}.yaml"

    def database_file(self) -> Path:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def get_settings() -> Settings:
    return Settings()
