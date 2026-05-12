"""Persistence helpers for `WelcomeConfig` (single row id=1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.welcome_config import WelcomeConfig


async def get_or_create_welcome(session: AsyncSession) -> WelcomeConfig:
    res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.id == 1))
    row = res.scalar_one_or_none()
    if row:
        return row
    row = WelcomeConfig(id=1, enabled=False)
    session.add(row)
    await session.flush()
    return row
