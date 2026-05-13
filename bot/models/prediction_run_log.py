"""Append-only log rows for prediction cycles (stats + audit)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class PredictionRunLog(Base):
    __tablename__ = "prediction_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    set_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    manual_test: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
