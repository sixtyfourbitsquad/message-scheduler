"""
Welcome message configuration for new channel subscribers.

When a user joins the configured public channel, handlers/welcome_members.py sends
this payload as a **private message** (if Telegram allows: user must have /start the bot).

Existing PostgreSQL databases need:
ALTER TABLE welcome_messages ADD COLUMN IF NOT EXISTS content_json JSONB;
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class WelcomeConfig(Base):
    __tablename__ = "welcome_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Serialized post (from message_to_content_dict). When set, takes precedence over text/media_json.
    content_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    buttons_json: Mapped[Optional[list[list[dict[str, str]]]]] = mapped_column(JSONB, nullable=True)
    delete_after_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
