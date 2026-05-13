"""Persistence for `/start` reply (single row)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.start_reply_config import StartReplyConfig


async def get_or_create_start_reply(session: AsyncSession) -> StartReplyConfig:
    res = await session.execute(select(StartReplyConfig).where(StartReplyConfig.id == 1))
    row = res.scalar_one_or_none()
    if row:
        return row
    row = StartReplyConfig(id=1, enabled=False, content_json={})
    session.add(row)
    await session.flush()
    return row


def effective_start_payload(
    row: StartReplyConfig,
) -> tuple[dict[str, Any], Optional[list[list[dict[str, str]]]]] | None:
    """Return (content, buttons) to send if enabled and content is valid; else None."""
    if not row.enabled:
        return None
    content = row.content_json or {}
    ctype = content.get("type")
    if not ctype or ctype == "unsupported":
        return None
    return content, row.buttons_json
