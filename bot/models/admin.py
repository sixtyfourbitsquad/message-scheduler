"""Dashboard admins stored in PostgreSQL (in addition to env allow-list)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class Admin(Base):
    """
    Optional persisted admin row for auditing.

    Primary access control still uses `ADMIN_TELEGRAM_IDS` from environment
    for simplicity and to avoid lock-out if DB is empty.
    """

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
