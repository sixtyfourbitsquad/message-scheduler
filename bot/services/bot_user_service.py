"""Record users who interact with the bot (for statistics)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User

from bot.models.bot_user import BotUser


async def record_bot_user_touch(session: AsyncSession, user: User) -> None:
    """Upsert `last_seen_at` (and username) for dashboard / active-user counts."""
    now = datetime.now(tz=timezone.utc)
    stmt = (
        insert(BotUser)
        .values(
            telegram_user_id=int(user.id),
            username=user.username,
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[BotUser.telegram_user_id],
            set_={
                "last_seen_at": now,
                "username": user.username,
            },
        )
    )
    await session.execute(stmt)
