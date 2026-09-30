from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEMO_ENVIRONMENTS = ("local", "test", "demo")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def parse_host_allowlist(raw: str) -> frozenset[tuple[str, int | None]]:
    entries: set[tuple[str, int | None]] = set()
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        parsed = urlsplit(f"//{value}")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"ALLOWED_PRIVATE_WEBHOOK_HOSTS: неверный порт в {value!r}") from exc
        if not parsed.hostname or parsed.path or parsed.username or parsed.password:
            raise ValueError(
                f"ALLOWED_PRIVATE_WEBHOOK_HOSTS: ожидается host[:port], а не {value!r}"
            )
        entries.add((parsed.hostname, port))
    return frozenset(entries)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_env: Literal["local", "test", "demo", "prod"] = "prod"
    database_url: str = "postgresql+asyncpg://repair:repair@127.0.0.1:54329/repair"
    public_base_url: str = "http://localhost:8080"

    max_api_base_url: str = "https://platform-api2.max.ru"
    max_bot_token: str = ""
    max_webhook_secret: str = ""
    max_webhook_secret_previous: str = ""
    max_webhook_rotation_window_seconds: int = 24 * 3600
    max_webhook_rotation_grace_seconds: int = 15 * 60
    max_updates_mode: Literal["webhook", "polling", "off"] = "off"
    max_bot_username: str = ""
    max_webapp_mode: Literal["mini_app", "link"] = "mini_app"

    bot_dialog_ttl_seconds: int = 30 * 60
    bot_action_ttl_seconds: int = 24 * 3600
    bot_subscription_check_interval_seconds: int = 15 * 60

    init_data_max_age_seconds: int = 300
    init_data_clock_skew_seconds: int = 60
    session_absolute_ttl_seconds: int = 12 * 3600
    session_idle_ttl_seconds: int = 2 * 3600
    login_link_ttl_seconds: int = 300
    bot_open_app_action_ttl_seconds: int = 30 * 24 * 3600
    demo_login_enabled: bool = False
    demo_showcase_enabled: bool = False
    demo_login_with_real_bot: bool = False
    auth_rate_limit_attempts: int = 20
    auth_rate_limit_window_seconds: int = 60

    staff_invitation_ttl_seconds: int = 24 * 3600
    binding_invitation_ttl_seconds: int = 7 * 24 * 3600

    binding_request_limit: int = 5
    binding_request_window_seconds: int = 15 * 60
    binding_request_provider_limit: int = 100

    own_service_reminder_critical_seconds: int = 30 * 60
    own_service_reminder_seconds: int = 2 * 3600
    assignment_confirm_critical_seconds: int = 30 * 60
    assignment_confirm_seconds: int = 2 * 3600
    offer_default_ttl_seconds: int = 24 * 3600
    offer_max_ttl_seconds: int = 72 * 3600
    search_window_seconds: int = 24 * 3600
    visit_proposal_default_ttl_seconds: int = 24 * 3600
    repair_quote_default_ttl_seconds: int = 72 * 3600
    proposal_max_ttl_seconds: int = 72 * 3600
    cancel_dispute_timeout_seconds: int = 72 * 3600
    auto_close_days: int = 0

    idempotency_ttl_seconds: int = 7 * 24 * 3600
    events_retention_days: int = 30
    events_page_max_limit: int = 100
    webhook_timeout_seconds: float = 10.0
    webhook_retry_window_seconds: int = 24 * 3600
    allowed_private_webhook_hosts: str = ""
    allow_private_webhook_hosts: bool = False
    secrets_encryption_key: str = Field(
        default="",
        description="Fernet-ключи секретов вебхуков через запятую; первым шифруется, "
        "остальные — только для расшифровки при ротации",
    )

    integration_rate_limit_rps: float = 10.0
    integration_rate_limit_burst: int = 20
    integration_auth_failure_rps: float = 0.2
    integration_auth_failure_burst: int = 10
    integration_auth_failure_ip_rps: float = 1.0
    integration_auth_failure_ip_burst: int = 50

    feed_dispatch_interval_seconds: float = 1.0
    feed_dispatch_batch: int = 500
    webhook_dispatch_interval_seconds: float = 1.0
    webhook_enqueue_batch: int = 500
    webhook_send_batch: int = 20
    webhook_lease_seconds: int = 120
    webhook_retry_base_seconds: float = 5.0
    webhook_retry_max_seconds: float = 3600.0
    notification_dispatch_interval_seconds: float = 1.0
    notification_send_batch: int = 20
    notification_lease_seconds: int = 120
    notification_max_attempts: int = 5
    notification_retry_base_seconds: float = 15.0
    notification_retry_max_seconds: float = 900.0
    max_per_chat_rps: float = 2.0
    max_global_rps: float = 30.0
    cleanup_interval_seconds: float = 3600.0
    verification_expiry_interval_seconds: float = 3600.0
    cleanup_batch: int = 1000
    max_update_lease_seconds: int = 300
    max_update_max_attempts: int = 5
    max_update_retry_base_seconds: float = 30.0
    max_update_retry_max_seconds: float = 1800.0
    max_update_recovery_interval_seconds: float = 15.0
    max_update_recovery_batch: int = 20
    max_updates_retention_days: int = 7
    max_updates_payload_retention_days: int = 14
    notifications_retention_days: int = 30

    worker_heartbeat_interval_multiplier: float = 3.0
    worker_heartbeat_grace_seconds: int = 300
    worker_heartbeat_write_seconds: float = 15.0
    ops_monitor_interval_seconds: float = 60.0
    ops_token: str = ""
    ops_allowed_networks: str = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    ops_failed_window_seconds: int = 3600
    ops_loop_failures_max: int = 5
    ops_notification_max_age_seconds: int = 600
    ops_notification_failed_max: int = 10
    ops_webhook_overdue_max_seconds: int = 600
    ops_webhook_failed_max: int = 20
    ops_max_updates_failed_max: int = 0

    file_storage_driver: Literal["local", "s3"] = "local"
    file_storage_path: str = "var/files"
    max_upload_bytes: int = 10 * 1024 * 1024
    upload_body_overhead_bytes: int = 256 * 1024
    max_request_body_bytes: int = 1024 * 1024
    max_image_pixels: int = 25_000_000
    max_photos_per_request: int = 10
    max_photos_per_equipment: int = 20
    keep_originals: bool = False
    portfolio_max_images: int = 10
    review_max_photos: int = 5
    orphan_files_min_age_days: int = 1

    image_processing_interval_seconds: float = 1.0
    image_processing_batch: int = 10
    image_processing_lease_seconds: int = 120
    image_processing_timeout_seconds: float = 10.0
    image_processing_memory_bytes: int = 512 * 1024 * 1024
    image_processing_max_attempts: int = 3
    rejected_files_retention_days: int = 7
    revoked_copies_retention_days: int = 7

    sweeper_interval_seconds: int = 15
    supported_currency: str = "RUB"

    review_text_max_length: int = 4000
    review_reply_max_length: int = 2000
    complaint_description_max_length: int = 2000
    complaint_limit: int = 10
    complaint_window_seconds: int = 24 * 3600
    rating_min_unique_orgs: int = 3
    rating_no_reviews_label: str = "Мало отзывов"

    fraud_order_spike_count: int = 5
    fraud_order_spike_window_hours: int = 72
    fraud_fast_completion_minutes: int = 15
    fraud_new_org_days: int = 14

    @property
    def is_demo_environment(self) -> bool:
        return self.app_env in _DEMO_ENVIRONMENTS

    @property
    def bot_enabled(self) -> bool:
        return bool(self.max_bot_token) and self.max_updates_mode != "off"

    @property
    def private_webhook_hosts(self) -> frozenset[tuple[str, int | None]]:
        return parse_host_allowlist(self.allowed_private_webhook_hosts)

    @property
    def operator_demo_login_allowed(self) -> bool:
        return self.app_env == "local" and not self.bot_enabled

    @property
    def max_upload_request_bytes(self) -> int:
        return self.max_upload_bytes + self.upload_body_overhead_bytes

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        problems: list[str] = []
        if self.allow_private_webhook_hosts:
            problems.append(
                "ALLOW_PRIVATE_WEBHOOK_HOSTS больше не поддерживается: перечислите нужные "
                "хосты в ALLOWED_PRIVATE_WEBHOOK_HOSTS (например, onec-connector:8083)"
            )
        if self.demo_login_enabled and self.bot_enabled and not self.demo_login_with_real_bot:
            problems.append(
                "DEMO_LOGIN_ENABLED вместе с настоящим ботом (MAX_BOT_TOKEN и "
                "MAX_UPDATES_MODE не off): стенд виден реальным пользователям MAX. "
                "Выключите demo-вход или подтвердите DEMO_LOGIN_WITH_REAL_BOT=true"
            )
        if self.max_webhook_secret_previous:
            if not self.max_webhook_secret:
                problems.append(
                    "MAX_WEBHOOK_SECRET_PREVIOUS задан без MAX_WEBHOOK_SECRET: при ротации "
                    "нужны оба значения"
                )
            elif self.max_webhook_secret_previous == self.max_webhook_secret:
                problems.append(
                    "MAX_WEBHOOK_SECRET_PREVIOUS совпадает с MAX_WEBHOOK_SECRET: укажите "
                    "прежнее значение секрета или уберите переменную"
                )
        if self.max_webhook_rotation_window_seconds <= 0:
            problems.append("MAX_WEBHOOK_ROTATION_WINDOW_SECONDS должен быть больше нуля")
        if self.max_webhook_rotation_grace_seconds < 0:
            problems.append("MAX_WEBHOOK_ROTATION_GRACE_SECONDS не может быть отрицательным")
        try:
            parse_host_allowlist(self.allowed_private_webhook_hosts)
        except ValueError as exc:
            problems.append(str(exc))
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _check_prod(self) -> "Settings":
        if self.app_env != "prod":
            return self
        problems: list[str] = []
        base = urlsplit(self.public_base_url)
        if base.scheme != "https" and base.hostname not in _LOCAL_HOSTS:
            problems.append("PUBLIC_BASE_URL должен начинаться с https:// при APP_ENV=prod")
        if not self.max_bot_token:
            problems.append("MAX_BOT_TOKEN обязателен: без него initData не проверить")
        if self.max_updates_mode == "webhook" and not self.max_webhook_secret:
            problems.append("MAX_WEBHOOK_SECRET обязателен при MAX_UPDATES_MODE=webhook")
        if self.allowed_private_webhook_hosts.strip():
            problems.append("ALLOWED_PRIVATE_WEBHOOK_HOSTS запрещён при APP_ENV=prod")
        if problems:
            raise ValueError("; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
