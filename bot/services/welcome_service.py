"""Persistence helpers for `WelcomeConfig` (single row id=1)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.welcome_config import WelcomeConfig


def effective_welcome_content(w: WelcomeConfig) -> dict[str, Any] | None:
    """Normalize stored welcome into the same dict shape used by `send_content_to_chat`."""
    cj = w.content_json
    if isinstance(cj, dict):
        t = cj.get("type")
        if t and t != "unsupported":
            return cj
    mj = w.media_json
    if isinstance(mj, dict) and mj.get("file_id") and mj.get("type"):
        out: dict[str, Any] = {"type": mj["type"], "file_id": mj["file_id"]}
        if w.text:
            out["caption"] = w.text
        return out
    if w.text:
        return {"type": "text", "text": w.text}
    return None


async def get_or_create_welcome(session: AsyncSession) -> WelcomeConfig:
    res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.id == 1))
    row = res.scalar_one_or_none()
    if row:
        return row
    row = WelcomeConfig(id=1, enabled=False)
    session.add(row)
    await session.flush()
    return row
