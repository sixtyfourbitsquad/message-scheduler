"""Single-row config for the message users receive when they send /start in private."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class StartReplyConfig(Base):
    """
    One row `id=1`: content + optional URL buttons shown on /start (non-admins always when enabled;
    admins see this first, then the control panel).
    """

    __tablename__ = "start_reply_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    buttons_json: Mapped[Optional[list[list[dict[str, str]]]]] = mapped_column(JSONB, nullable=True)
