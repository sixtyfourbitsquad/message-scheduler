"""`/start` entry — only slash command besides inline navigation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config.settings import settings
from bot.database.session import get_session_factory
from bot.handlers.helpers import DASHBOARD_HTML
from bot.keyboards.inline import kb_main_menu
from bot.services.bot_user_service import record_bot_user_touch
from bot.services.welcome_dm import send_welcome_for_subscriber
from bot.services.welcome_service import get_or_create_welcome
from bot.utils.fsm import reset_fsm

_NON_ADMIN_START = (
    "You're on the list for channel updates in this chat. "
    "If you joined the channel before tapping Start here, your welcome message will arrive now."
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admins get the dashboard; anyone else gets a short line so the bot may DM them later."""
    user = update.effective_user
    if not user:
        return

    factory = get_session_factory()
    async with factory() as session:
        await record_bot_user_touch(session, user)
        w = await get_or_create_welcome(session)
        delete_after = w.delete_after_seconds
        await send_welcome_for_subscriber(
            context.bot,
            session,
            user_id=int(user.id),
            delete_after_seconds=delete_after,
        )
        await session.commit()

    if user.id not in settings.admin_id_set:
        await update.message.reply_text(_NON_ADMIN_START)
        return

    reset_fsm(context.user_data)
    await update.message.reply_html(DASHBOARD_HTML, reply_markup=kb_main_menu())
