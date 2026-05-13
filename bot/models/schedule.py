"""
Scheduled posts: one-time, daily, weekly, or custom interval.

`content_json` stores serialized message payload (text/media file_ids).
`buttons_json` stores inline keyboard layout for resend.

`daily_slot_times`: optional list of "HH:MM" strings (same `kind=daily`); one APScheduler job per slot.

`content_pool_json`: optional list of message payloads; each run picks one at random (e.g. many
prediction texts). Fill via SQL/API or a future UI — same shape as `message_to_content_dict` output.

`jitter_seconds`: optional max random delay after the cron fires (capped in code).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class ScheduleKind(str, Enum):
    """High-level schedule classification used by the UI and APScheduler."""

    once = "once"
    daily = "daily"
    weekly = "weekly"
    interval = "interval"


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="Scheduled post")

    kind: Mapped[str] = mapped_column(String(32), index=True)  # ScheduleKind value

    # For `once`: next fire time. For recurring: anchor / last computed next run (UTC).
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Human display label e.g. "Mon 21:00"
    schedule_summary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Recurrence parameters (interpretation depends on `kind`)
    # daily/weekly: "HH:MM" 24h in `timezone` from AppSettings at save time
    time_hhmm: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # weekly: 0=Mon .. 6=Sun (Python weekday convention)
    weekday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # interval: seconds between runs
    interval_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # When set (e.g. 6 IST peak times), `kind` stays `daily` and one APScheduler job is created per slot.
    daily_slot_times: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    # If non-empty, each run picks one entry at random (predictions / bulk). Otherwise uses `content_json`.
    content_pool_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    # Max random delay in seconds after the cron fires (0 = none). Spreads load slightly.
    jitter_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")

    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    buttons_json: Mapped[Optional[list[list[dict[str, str]]]]] = mapped_column(JSONB, nullable=True)

    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    apscheduler_job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
