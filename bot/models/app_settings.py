"""Singleton-style application settings row (one channel, optional discussion group)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class AppSettings(Base):
    """
    Stores runtime configuration editable from the Settings panel.

    We keep a single row with `id = 1` for simplicity (easy upsert).
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Target public channel (numeric ID, often negative like -100...)
    target_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Optional linked discussion supergroup (legacy / manual use)
    discussion_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    logs_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
