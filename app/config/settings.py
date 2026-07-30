from pydantic import Field, SecretStr
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
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


settings = Settings()
