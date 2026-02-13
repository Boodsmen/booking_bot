"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Bot configuration from environment variables."""

    # Bot
    bot_token: str = Field(..., alias="BOT_TOKEN")

    # Database
    db_host: str = Field(default="db", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="booking_bot", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")

    # Timezone
    timezone: str = Field(default="Europe/Moscow", alias="TIMEZONE")

    # Default admin (for initial setup)
    default_admin_id: int | None = Field(default=None, alias="DEFAULT_ADMIN_ID")

    # Timing settings
    reminder_minutes_before: int = Field(default=15, alias="REMINDER_MINUTES_BEFORE")
    confirmation_timeout_minutes: int = Field(default=15, alias="CONFIRMATION_TIMEOUT_MINUTES")
    overdue_alert_minutes: int = Field(default=30, alias="OVERDUE_ALERT_MINUTES")

    # Anti-abuse limits
    max_booking_duration_hours: int = Field(default=72, alias="MAX_BOOKING_DURATION_HOURS")
    max_future_booking_days: int = Field(default=30, alias="MAX_FUTURE_BOOKING_DAYS")

    @property
    def database_url(self) -> str:
        """Build async PostgreSQL connection string."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Singleton instance
settings = Settings()
