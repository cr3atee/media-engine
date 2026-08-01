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
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SCHEDULER_",
        extra="ignore",
    )

    timezone: str = "UTC"


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
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


settings = Settings()
