from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DATABASE_",
        extra="ignore",
    )

    url: str = "postgresql+asyncpg://postgres:postgres@db:5432/mediaengine"
    echo: bool = False


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TELEGRAM_",
        extra="ignore",
    )

    bot_token: SecretStr = SecretStr("")
    chat_id: str = ""
    api_base_url: str = "https://api.telegram.org"
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    disable_web_page_preview: bool = True
    maximum_message_length: int = Field(default=4096, ge=1, le=4096)
    delivery_enabled: bool = False
    dry_run: bool = True
    allow_live_delivery: bool = False
    test_chat_id: str = ""
    allowed_destination_ids: list[str] = Field(default_factory=list)
    delivery_batch_size: int = Field(default=10, gt=0)
    publication_lease_seconds: int = Field(default=60, gt=0)
    maximum_attempts: int = Field(default=5, gt=0)
    initial_retry_seconds: int = Field(default=30, gt=0)
    maximum_retry_seconds: int = Field(default=1800, gt=0)

    @model_validator(mode="after")
    def validate_delivery_safety(self) -> "TelegramSettings":
        if self.maximum_retry_seconds < self.initial_retry_seconds:
            msg = "Telegram maximum retry delay must not be below initial retry delay."
            raise ValueError(msg)
        if (
            self.delivery_enabled
            and self.publication_lease_seconds <= self.request_timeout_seconds
        ):
            msg = "Telegram publication lease must exceed request timeout."
            raise ValueError(msg)
        if self.delivery_enabled and not self.dry_run:
            if not self.allow_live_delivery:
                msg = "Live Telegram delivery requires TELEGRAM_ALLOW_LIVE_DELIVERY."
                raise ValueError(msg)
            if not self.bot_token.get_secret_value().strip():
                msg = "Live Telegram delivery requires TELEGRAM_BOT_TOKEN."
                raise ValueError(msg)
            if not self.allowed_destination_ids:
                msg = "Live Telegram delivery requires allowlisted destinations."
                raise ValueError(msg)
        return self


class OpenRouterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OPENROUTER_",
        extra="ignore",
    )

    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = ""


class SchedulerSettings(BaseSettings):
    """Configuration for scheduler orchestration and optional lease guarding."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SCHEDULER_",
        extra="ignore",
    )

    timezone: str = "UTC"
    tick_seconds: float = Field(default=0.25, gt=0)
    lease_enabled: bool = False
    owner_id: str = Field(default="", max_length=255)
    lease_ttl_seconds: float = Field(default=300.0, gt=0)


class EventProcessingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EVENT_PROCESSING_",
        extra="ignore",
    )

    scoring_batch_size: int = Field(default=50, gt=0)
    scoring_lease_seconds: int = Field(default=60, gt=0)
    scoring_maximum_attempts: int = Field(default=3, gt=0)
    scoring_initial_retry_seconds: int = Field(default=5, gt=0)
    scoring_maximum_retry_seconds: int = Field(default=300, gt=0)
    stale_claim_recovery_batch_size: int = Field(default=50, gt=0)
    stale_claim_recovery_interval_seconds: int = Field(default=30, gt=0)


class ContentProcessingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CONTENT_PROCESSING_",
        extra="ignore",
    )

    batch_size: int = Field(default=20, gt=0)
    lease_seconds: int = Field(default=120, gt=0)
    maximum_attempts: int = Field(default=5, gt=0)
    initial_retry_seconds: int = Field(default=30, gt=0)
    maximum_retry_seconds: int = Field(default=1800, gt=0)
    stale_content_batch_size: int = Field(default=50, gt=0)
    stale_content_recovery_interval_seconds: int = Field(default=60, gt=0)
    stale_publication_batch_size: int = Field(default=50, gt=0)
    stale_publication_recovery_interval_seconds: int = Field(default=60, gt=0)
    content_type: str = "telegram_post"
    language: str = "ru"
    provider_label: str = "configured"
    model_label: str = "configured"
    prompt_version: str = "price_drop_v1"
    publication_channel: str = ""
    publication_destination_key: str = ""


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LOG_",
        extra="ignore",
    )

    level: str = "INFO"


class DiagnosticSettings(BaseSettings):
    """Sanitized incident persistence and bounded fallback policy."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DIAGNOSTICS_",
        extra="ignore",
    )

    environment: str = Field(default="development", min_length=1, max_length=64)
    release: str = Field(default="unknown", min_length=1, max_length=128)
    retention_days: int = Field(default=30, ge=1, le=365)
    fallback_path: Path = Path("var/diagnostics/incidents.jsonl")
    fallback_max_bytes: int = Field(default=5_000_000, ge=1024)
    fallback_backups: int = Field(default=3, ge=1, le=20)
    persistence_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    fallback_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    frontend_reports_per_minute: int = Field(default=12, ge=1, le=120)


class OperationalAlertingSettings(BaseSettings):
    """Opt-in runtime alert evaluation and lifecycle policy."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ALERTING_",
        extra="ignore",
    )

    enabled: bool = False
    evaluation_interval_seconds: float = Field(default=30.0, gt=0)
    dashboard_window_seconds: int = Field(default=86_400, gt=0)
    reminder_interval_seconds: int = Field(default=1800, gt=0)


class PollingRetentionSettings(BaseSettings):
    """Fail-closed scheduling configuration for polling-history retention."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="POLLING_RETENTION_",
        extra="ignore",
    )

    enabled: bool = False
    interval_seconds: int | None = Field(default=None, gt=0)
    retain_for_seconds: int | None = Field(default=None, gt=0)
    keep_latest_per_integration: int | None = Field(default=None, ge=1)
    batch_size: int | None = Field(default=None, gt=0)
    retry_count: int = Field(default=0, ge=0)
    retry_delay_seconds: float = Field(default=0.0, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_enabled_policy(self) -> "PollingRetentionSettings":
        """Require every deployment-owned policy value when scheduling is enabled."""
        if not self.enabled:
            return self
        required_values = {
            "interval_seconds": self.interval_seconds,
            "retain_for_seconds": self.retain_for_seconds,
            "keep_latest_per_integration": self.keep_latest_per_integration,
            "batch_size": self.batch_size,
            "timeout_seconds": self.timeout_seconds,
        }
        missing = tuple(
            name for name, value in required_values.items() if value is None
        )
        if missing:
            msg = (
                "Enabled polling retention requires explicit values for: "
                + ", ".join(missing)
                + "."
            )
            raise ValueError(msg)
        return self


class AdminApiSettings(BaseSettings):
    """Configuration for the authenticated administration API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ADMIN_",
        extra="ignore",
    )

    api_enabled: bool = False
    api_key: SecretStr = SecretStr("")
    test_bypass_enabled: bool = False
    api_docs_enabled: bool = True
    default_page_size: int = Field(default=50, ge=1, le=100)
    maximum_page_size: int = Field(default=100, ge=1, le=500)
    request_id_max_length: int = Field(default=128, ge=16, le=256)
    cursor_signing_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_page_sizes(self) -> "AdminApiSettings":
        if self.maximum_page_size < self.default_page_size:
            msg = "Admin API maximum page size must not be below the default."
            raise ValueError(msg)
        return self


class AuthSettings(BaseSettings):
    """Configuration for seller authentication and tenant authorization."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AUTH_",
        extra="ignore",
    )

    access_token_secret: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = Field(default=900, gt=0)
    refresh_token_ttl_seconds: int = Field(default=2_592_000, gt=0)
    password_reset_token_ttl_seconds: int = Field(default=3600, gt=0)
    token_issuer: str = "mediaengine"
    token_audience: str = "mediaengine-seller-api"
    password_hash_iterations: int = Field(default=210_000, ge=100_000)

    @model_validator(mode="after")
    def validate_token_secret(self) -> "AuthSettings":
        if self.access_token_ttl_seconds >= self.refresh_token_ttl_seconds:
            msg = "Auth access token TTL must be lower than refresh token TTL."
            raise ValueError(msg)
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    openrouter: OpenRouterSettings = Field(default_factory=OpenRouterSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    event_processing: EventProcessingSettings = Field(
        default_factory=EventProcessingSettings
    )
    content_processing: ContentProcessingSettings = Field(
        default_factory=ContentProcessingSettings
    )
    admin_api: AdminApiSettings = Field(default_factory=AdminApiSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    diagnostics: DiagnosticSettings = Field(default_factory=DiagnosticSettings)
    alerting: OperationalAlertingSettings = Field(
        default_factory=OperationalAlertingSettings
    )
    polling_retention: PollingRetentionSettings = Field(
        default_factory=PollingRetentionSettings
    )


settings = Settings()
