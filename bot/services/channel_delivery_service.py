"""Append-only log of successful channel posts (broadcast + scheduler)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.channel_delivery_log import ChannelDeliveryLog


async def record_channel_delivery(
    session: AsyncSession,
    *,
    channel_id: int,
    kind: str,
    admin_id: int | None = None,
    schedule_id: int | None = None,
) -> None:
    session.add(
        ChannelDeliveryLog(
            channel_id=int(channel_id),
            kind=kind,
            admin_id=admin_id,
            schedule_id=schedule_id,
        )
    )
