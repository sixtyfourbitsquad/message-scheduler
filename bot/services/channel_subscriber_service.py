"""Channel join/leave registry for subscriber broadcasts and welcome tracking."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User

from bot.models.channel_subscriber import ChannelSubscriber


async def record_channel_join(session: AsyncSession, *, channel_id: int, user: User) -> ChannelSubscriber:
    """Upsert subscriber on join; clears welcome lock so rejoiners can get welcome again."""
    now = datetime.now(tz=timezone.utc)
    uid = int(user.id)
    row = await session.get(ChannelSubscriber, uid)
    if row:
        row.channel_id = int(channel_id)
        row.username = user.username
        row.joined_channel_at = now
        row.left_channel_at = None
        row.unsubscribed = False
        row.welcome_sent_at = None
        return row
    row = ChannelSubscriber(
        telegram_user_id=uid,
        channel_id=int(channel_id),
        username=user.username,
        joined_channel_at=now,
        unsubscribed=False,
    )
    session.add(row)
    return row


async def record_channel_leave(session: AsyncSession, *, channel_id: int, user_id: int) -> None:
    now = datetime.now(tz=timezone.utc)
    row = await session.get(ChannelSubscriber, int(user_id))
    if not row or int(row.channel_id) != int(channel_id):
        return
    row.unsubscribed = True
    row.left_channel_at = now


async def list_active_subscriber_ids(session: AsyncSession) -> list[int]:
    res = await session.execute(
        select(ChannelSubscriber.telegram_user_id).where(ChannelSubscriber.unsubscribed.is_(False))
    )
    return [int(r[0]) for r in res.all()]


async def count_active_subscribers(session: AsyncSession) -> int:
    n = await session.scalar(
        select(func.count()).select_from(ChannelSubscriber).where(ChannelSubscriber.unsubscribed.is_(False))
    )
    return int(n or 0)


async def count_pending_welcome(session: AsyncSession) -> int:
    n = await session.scalar(
        select(func.count())
        .select_from(ChannelSubscriber)
        .where(ChannelSubscriber.unsubscribed.is_(False), ChannelSubscriber.welcome_sent_at.is_(None))
    )
    return int(n or 0)
