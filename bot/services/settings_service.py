"""Persistence helpers for `AppSettings`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config.settings import settings as env_settings
from bot.models.app_settings import AppSettings


async def get_or_create_settings(session: AsyncSession) -> AppSettings:
    """Return settings id=1, creating with sane defaults if missing."""
    res = await session.execute(select(AppSettings).where(AppSettings.id == 1))
    row = res.scalar_one_or_none()
    if row:
        return row
    row = AppSettings(
        id=1,
        timezone=env_settings.default_timezone,
        logs_enabled=True,
    )
    session.add(row)
    await session.flush()
    return row
