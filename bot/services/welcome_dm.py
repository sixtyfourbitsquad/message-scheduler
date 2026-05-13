"""Send configured welcome DM to a subscriber row (updates welcome_sent_at on success)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import Forbidden, TelegramError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.channel_subscriber import ChannelSubscriber
from bot.services.content_poster import send_content_to_chat
from bot.services.welcome_service import effective_welcome_content, get_or_create_welcome

log = logging.getLogger(__name__)


async def send_welcome_for_subscriber(
    bot: Bot,
    session: AsyncSession,
    *,
    user_id: int,
    delete_after_seconds: int | None = None,
) -> int | None:
    """
    If welcome is enabled and subscriber exists and welcome not yet sent, DM once.

    Returns message_id if a message was sent, else None.
    """
    sub = await session.get(ChannelSubscriber, int(user_id))
    if not sub or sub.unsubscribed or sub.welcome_sent_at is not None:
        return None

    w = await get_or_create_welcome(session)
    if not w.enabled:
        return None

    content = effective_welcome_content(w)
    if not content:
        return None

    buttons = w.buttons_json
    try:
        mid = await send_content_to_chat(
            bot,
            chat_id=int(user_id),
            content=content,
            buttons_json=buttons,
        )
    except Forbidden:
        log.info("welcome DM blocked for user %s (must /start bot first)", user_id)
        return None
    except TelegramError as e:
        log.warning("welcome DM failed for user %s: %s", user_id, e)
        return None

    if not mid:
        return None

    sub.welcome_sent_at = datetime.now(tz=timezone.utc)

    if delete_after_seconds and int(delete_after_seconds) > 0:

        async def _delete_later() -> None:
            await asyncio.sleep(int(delete_after_seconds))
            try:
                await bot.delete_message(chat_id=int(user_id), message_id=mid)
            except Exception as e:
                log.info("welcome auto-delete failed: %s", e)

        asyncio.create_task(_delete_later())

    return mid
