"""Failed channel deliveries (broadcasts or scheduled posts)."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class FailedDelivery(Base):
    __tablename__ = "failed_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    context: Mapped[str] = mapped_column(String(64))  # broadcast | schedule
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str] = mapped_column(Text)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
