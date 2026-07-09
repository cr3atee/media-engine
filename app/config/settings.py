from pydantic import Field
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

    bot_token: str = ""
    chat_id: str = ""


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
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


settings = Settings()
