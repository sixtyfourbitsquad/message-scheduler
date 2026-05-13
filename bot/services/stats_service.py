"""Aggregate statistics for the admin dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.bot_user import BotUser
from bot.models.broadcast_log import BroadcastLog
from bot.models.channel_delivery_log import ChannelDeliveryLog
from bot.models.failed_delivery import FailedDelivery
from bot.models.schedule import Schedule
from bot.services.channel_subscriber_service import count_active_subscribers, count_pending_welcome


async def stats_snapshot(session: AsyncSession, *, started_at: datetime) -> dict[str, Any]:
    """Return counters for the Statistics panel."""
    now = datetime.now(tz=timezone.utc)
    since_7 = now - timedelta(days=7)
    since_30 = now - timedelta(days=30)

    total_broadcasts = await session.scalar(select(func.count()).select_from(BroadcastLog))
    total_schedules = await session.scalar(select(func.count()).select_from(Schedule))
    active_schedules = await session.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.paused.is_(False))
    )
    failed_deliveries = await session.scalar(select(func.count()).select_from(FailedDelivery))

    total_bot_users = await session.scalar(select(func.count()).select_from(BotUser))
    active_users_7d = await session.scalar(
        select(func.count()).select_from(BotUser).where(BotUser.last_seen_at >= since_7)
    )
    active_users_30d = await session.scalar(
        select(func.count()).select_from(BotUser).where(BotUser.last_seen_at >= since_30)
    )
    channel_posts_logged = await session.scalar(select(func.count()).select_from(ChannelDeliveryLog))

    active_subscribers = await count_active_subscribers(session)
    pending_welcome = await count_pending_welcome(session)

    uptime = now - started_at.replace(tzinfo=timezone.utc)
    return {
        "total_broadcasts": int(total_broadcasts or 0),
        "total_schedules": int(total_schedules or 0),
        "active_schedules": int(active_schedules or 0),
        "failed_deliveries": int(failed_deliveries or 0),
        "uptime_seconds": int(uptime.total_seconds()),
        "total_bot_users": int(total_bot_users or 0),
        "active_users_7d": int(active_users_7d or 0),
        "active_users_30d": int(active_users_30d or 0),
        "channel_posts_logged": int(channel_posts_logged or 0),
        "active_subscribers": int(active_subscribers),
        "pending_welcome": int(pending_welcome),
    }
