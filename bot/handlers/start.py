"""`/start` entry — only slash command besides inline navigation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config.settings import settings
from bot.database.session import get_session_factory
from bot.handlers.helpers import DASHBOARD_HTML
from bot.keyboards.inline import kb_main_menu
from bot.services.bot_user_service import record_bot_user_touch
from bot.services.content_poster import send_content_to_chat
from bot.services.start_reply_service import effective_start_payload, get_or_create_start_reply
from bot.utils.fsm import reset_fsm

_NON_ADMIN_FALLBACK = (
    "This bot manages a channel for its admins. You do not need to use commands here unless you were asked to."
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Optional configured greeting for everyone; admins also get the inline control panel."""
    user = update.effective_user
    if not user:
        return

    factory = get_session_factory()
    async with factory() as session:
        await record_bot_user_touch(session, user)
        row = await get_or_create_start_reply(session)
        await session.commit()

    payload = effective_start_payload(row)
    greeting_sent = False
    if payload:
        content, buttons = payload
        mid = await send_content_to_chat(
            context.bot,
            chat_id=int(user.id),
            content=content,
            buttons_json=buttons,
        )
        greeting_sent = mid is not None

    is_admin = user.id in settings.admin_id_set
    if is_admin:
        reset_fsm(context.user_data)
        await update.message.reply_html(DASHBOARD_HTML, reply_markup=kb_main_menu())
        return

    if not payload:
        await update.message.reply_text(_NON_ADMIN_FALLBACK)
    elif not greeting_sent:
        await update.message.reply_text(
            "⚠️ The bot could not send the configured greeting. Please try again later or contact the admin."
        )
