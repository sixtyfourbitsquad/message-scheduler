"""
Central application settings loaded from environment variables.

Never commit real secrets — use `.env` locally and systemd EnvironmentFile on VPS.
"""

from functools import lru_cache
from typing import FrozenSet

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration with validation (Pydantic v2)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(..., description="Bot token from @BotFather")
    admin_telegram_ids: str = Field(
        ...,
        description="Comma-separated numeric user IDs of dashboard admins",
    )

    webhook_base_url: str = Field(..., description="HTTPS base URL, no trailing slash")
    webhook_path: str = Field(default="/webhook")
    webhook_secret_token: str = Field(..., min_length=8, description="Webhook secret for Telegram")

    database_url: str = Field(..., description="SQLAlchemy async URL, postgresql+asyncpg://...")

    duckdns_domain: str = Field(default="")
    duckdns_token: str = Field(default="")

    default_timezone: str = Field(default="Asia/Kolkata")
    log_level: str = Field(default="INFO")

    @field_validator("webhook_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def admin_id_set(self) -> FrozenSet[int]:
        """Frozen set of admin Telegram user IDs for O(1) membership checks."""
        parts = [p.strip() for p in self.admin_telegram_ids.split(",") if p.strip()]
        return frozenset(int(x) for x in parts)

    @property
    def full_webhook_url(self) -> str:
        """Full URL passed to Telegram setWebhook."""
        path = self.webhook_path if self.webhook_path.startswith("/") else f"/{self.webhook_path}"
        return f"{self.webhook_base_url}{path}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (safe for workers that fork before first use)."""
    return Settings()


settings = get_settings()
