"""Telegram channel / permission checks."""

from __future__ import annotations

import logging

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError

log = logging.getLogger(__name__)


async def user_can_manage_channel(bot: Bot, *, channel_id: int, user_id: int) -> bool:
    """
    Return True if `user_id` is creator/administrator with post rights in `channel_id`.

    Used to enforce "force channel admin verification" for the control panel.
    """
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except TelegramError as e:
        log.warning("get_chat_member failed: %s", e)
        return False

    status = member.status
    if status == ChatMemberStatus.CREATOR:
        return True
    if status == ChatMemberStatus.ADMINISTRATOR:
        # PTB v21: ChatMemberAdministrator has can_post_messages optional
        adm = getattr(member, "can_post_messages", None)
        if adm is True:
            return True
        # Some channel admin objects omit explicit False — treat unknown as True if admin
        if adm is None:
            return True
    return False
