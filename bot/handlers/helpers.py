"""Small Telegram UI helpers shared across handlers."""

from __future__ import annotations

import html
import logging
from typing import Optional

from telegram import InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

DASHBOARD_HTML = (
    "<b>🏠 CHANNEL CONTROL PANEL</b>\n\n"
    "Broadcast to your channel, build URL buttons, and schedule recurring or one-off posts.\n"
    "Use the buttons below — everything stays in one message when possible.\n"
)


async def edit_or_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = ParseMode.HTML,
) -> Message:
    """
    Prefer editing the dashboard/callback message; fall back to a new private message.

    This keeps the UX clean when Telegram refuses an edit (e.g. message too old).
    """
    q = update.callback_query
    if q and q.message:
        try:
            return await q.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except BadRequest as e:
            log.info("edit_text failed (%s) — sending new message", e)

    chat = update.effective_chat
    assert chat is not None
    return await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def esc(s: str) -> str:
    """Escape for HTML captions."""
    return html.escape(s, quote=True)
