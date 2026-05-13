"""Deliver the same broadcast payload to many subscribers in private (rate-limited)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot
from telegram.error import Forbidden, TelegramError

from bot.database.session import get_session_factory
from bot.services.channel_delivery_service import record_channel_delivery
from bot.services.content_poster import send_content_to_chat

log = logging.getLogger(__name__)

_DM_GAP_S = 0.035


async def fanout_dm_to_subscribers(
    bot: Bot,
    *,
    user_ids: list[int],
    content: dict[str, Any],
    buttons_json: list[list[dict[str, str]]] | None,
    channel_id: int,
    admin_id: int | None,
) -> tuple[int, int]:
    """Return (success_count, failure_count). Logs each success to `channel_delivery_logs`."""
    ok = 0
    fail = 0
    factory = get_session_factory()
    for uid in user_ids:
        try:
            mid = await send_content_to_chat(
                bot, chat_id=int(uid), content=content, buttons_json=buttons_json
            )
            if mid:
                ok += 1
                async with factory() as session:
                    await record_channel_delivery(
                        session,
                        channel_id=int(channel_id),
                        kind="subscriber_dm",
                        admin_id=admin_id,
                    )
                    await session.commit()
            else:
                fail += 1
        except Forbidden:
            fail += 1
        except TelegramError as e:
            log.info("subscriber DM failed uid=%s: %s", uid, e)
            fail += 1
        await asyncio.sleep(_DM_GAP_S)
    return ok, fail
