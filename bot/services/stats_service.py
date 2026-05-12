"""Aggregate statistics for the admin dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.broadcast_log import BroadcastLog
from bot.models.failed_delivery import FailedDelivery
from bot.models.schedule import Schedule


async def stats_snapshot(session: AsyncSession, *, started_at: datetime) -> dict[str, Any]:
    """Return counters for the Statistics panel."""
    total_broadcasts = await session.scalar(select(func.count()).select_from(BroadcastLog))
    total_schedules = await session.scalar(select(func.count()).select_from(Schedule))
    active_schedules = await session.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.paused.is_(False))
    )
    failed_deliveries = await session.scalar(select(func.count()).select_from(FailedDelivery))

    uptime = datetime.now(tz=timezone.utc) - started_at.replace(tzinfo=timezone.utc)
    return {
        "total_broadcasts": int(total_broadcasts or 0),
        "total_schedules": int(total_schedules or 0),
        "active_schedules": int(active_schedules or 0),
        "failed_deliveries": int(failed_deliveries or 0),
        "uptime_seconds": int(uptime.total_seconds()),
    }
