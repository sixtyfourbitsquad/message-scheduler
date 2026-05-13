"""Detect target channel joins/leaves: register subscribers, welcome in DM when possible."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.database.session import get_session_factory
from bot.services.channel_subscriber_service import record_channel_join, record_channel_leave
from bot.services.settings_service import get_or_create_settings
from bot.services.welcome_dm import send_welcome_for_subscriber
from bot.services.welcome_service import get_or_create_welcome


def _became_member(old: ChatMemberStatus, new: ChatMemberStatus) -> bool:
    return new in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and old not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }


def _became_left(old: ChatMemberStatus, new: ChatMemberStatus) -> bool:
    return old in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and new in {
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED,
    }


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Track subscribers on the configured public channel and send welcome DMs when allowed.

    Telegram only allows DMs after the user has opened the bot (`/start`); until then we
    still save them for subscriber broadcasts and deliver welcome on first `/start`.
    """
    res = update.chat_member
    if not res or res.chat.type != ChatType.CHANNEL:
        return

    factory = get_session_factory()
    async with factory() as session:
        cfg = await get_or_create_settings(session)
        if cfg.target_channel_id is None or int(res.chat.id) != int(cfg.target_channel_id):
            return

        old = res.old_chat_member.status
        new = res.new_chat_member.status
        user = res.new_chat_member.user
        if not user or user.is_bot:
            return

        uid = int(user.id)
        ch_id = int(res.chat.id)

        if _became_left(old, new):
            await record_channel_leave(session, channel_id=ch_id, user_id=uid)
            await session.commit()
            return

        if not _became_member(old, new):
            return

        await record_channel_join(session, channel_id=ch_id, user=user)
        await session.flush()
        w = await get_or_create_welcome(session)
        delete_after = w.delete_after_seconds
        await send_welcome_for_subscriber(
            context.bot,
            session,
            user_id=uid,
            delete_after_seconds=delete_after,
        )
        await session.commit()