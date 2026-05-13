"""One row per successful post to the target channel (broadcast or scheduler)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class ChannelDeliveryLog(Base):
    __tablename__ = "channel_delivery_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # broadcast | schedule
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
