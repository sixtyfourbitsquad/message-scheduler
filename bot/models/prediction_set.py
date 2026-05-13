"""Weighted prediction bundles (templates, stickers, images, captions) for the engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class PredictionSet(Base):
    """
    One logical "set" (e.g. ~1/20 of your library). `payload` holds pools:

    {
      "templates": [ { "type":"text", "text":"..." }, ... ],
      "win_stickers": [ "file_id", ... ],
      "loss_stickers": [ "file_id", ... ],
      "result_images": [ { "type":"photo", "file_id":"...", "caption":"..." }, ... ],
      "captions": [ "plain caption strings", ... ],
      "warnings": [ "optional short lines after the signal", ... ],
      "registers": [ "optional session register lines before the signal", ... ]
    }

    Pools are editable from the Telegram Prediction engine admin panel (no SQL required).
    """

    __tablename__ = "prediction_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), default="set")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
