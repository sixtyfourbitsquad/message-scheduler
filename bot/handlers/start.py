"""`/start` entry — only slash command besides inline navigation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config.settings import settings
from bot.handlers.helpers import DASHBOARD_HTML
from bot.keyboards.inline import kb_main_menu
from bot.utils.fsm import reset_fsm


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Private admins land on the dashboard."""
    user = update.effective_user
    if not user or user.id not in settings.admin_id_set:
        await update.message.reply_text("⛔ This bot is private.")
        return

    reset_fsm(context.user_data)
    await update.message.reply_html(DASHBOARD_HTML, reply_markup=kb_main_menu())
