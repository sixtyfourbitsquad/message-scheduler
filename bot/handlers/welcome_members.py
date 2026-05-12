"""Welcome new members in the linked discussion supergroup."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.database.session import get_session_factory
from bot.services.content_poster import send_welcome_to_group
from bot.services.settings_service import get_or_create_settings
from bot.services.welcome_service import get_or_create_welcome

log = logging.getLogger(__name__)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect joins in the configured discussion group and post the welcome message."""
    res = update.chat_member
    if not res:
        return

    old = res.old_chat_member.status
    new = res.new_chat_member.status

    became_member = new in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and old not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }
    if not became_member:
        return

    factory = get_session_factory()
    async with factory() as session:
        cfg = await get_or_create_settings(session)
        if cfg.discussion_group_id is None or int(res.chat.id) != int(cfg.discussion_group_id):
            return
        w = await get_or_create_welcome(session)
        if not w.enabled:
            return
        text = w.text
        media = w.media_json
        buttons = w.buttons_json
        delete_after = w.delete_after_seconds

    try:
        mid = await send_welcome_to_group(
            context.bot,
            group_chat_id=int(res.chat.id),
            text=text,
            media_json=media,
            buttons_json=buttons,
            reply_to_message_id=None,
        )
    except Exception as e:
        log.exception("welcome send failed: %s", e)
        return

    if delete_after and mid and int(delete_after) > 0:
        async def _delete_later() -> None:
            await asyncio.sleep(int(delete_after))
            try:
                await context.bot.delete_message(chat_id=res.chat.id, message_id=mid)
            except Exception as e:
                log.info("welcome auto-delete failed: %s", e)

        asyncio.create_task(_delete_later())
