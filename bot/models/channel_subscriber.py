"""Users detected joining the target channel (broadcast audience + welcome tracking)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class ChannelSubscriber(Base):
    """
    One row per Telegram user seen joining the configured public channel.

    Used for: deferred welcome DMs after `/start`, and optional broadcast fan-out.
    """

    __tablename__ = "channel_subscribers"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    joined_channel_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_channel_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
