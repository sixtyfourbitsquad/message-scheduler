"""Admin authorization and optional channel-post permission verification."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.config.settings import settings
from bot.database.session import get_session_factory
from bot.services.channel_service import user_can_manage_channel
from bot.services.settings_service import get_or_create_settings

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


def _is_settings_escape(update: Update) -> bool:
    """Allow configuring the target channel if current config is wrong."""
    q = update.callback_query
    if not q or not q.data:
        return False
    return q.data.startswith("cfg:") or q.data in {"m:home", "m:cfg"}


class AdminOnlyMiddleware:
    """
    Block any non-admin traffic early.

    If a target channel is configured, require dashboard users to be able to post there.
    If verification fails, still allow `/start` plus Settings menu callbacks so the channel
    ID can be corrected without redeploying.
    """

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        next_handler: Handler,
    ) -> Any:
        user = update.effective_user
        if user is None:
            raise ApplicationHandlerStop()

        if user.id not in settings.admin_id_set:
            if update.callback_query:
                await update.callback_query.answer("⛔ Not authorized", show_alert=True)
            elif update.message and update.message.text and update.message.text.strip().startswith("/start"):
                await update.message.reply_text("⛔ This bot is private.")
            elif update.message:
                await update.message.reply_text("⛔ This bot is private.")
            raise ApplicationHandlerStop()

        factory = get_session_factory()
        async with factory() as session:
            cfg = await get_or_create_settings(session)
            channel_id = cfg.target_channel_id

        if channel_id is None:
            return await next_handler(update, context)

        ok = await user_can_manage_channel(context.bot, channel_id=channel_id, user_id=user.id)
        if ok:
            return await next_handler(update, context)

        msg = (
            "⛔ You must be a channel administrator with permission to post messages.\n\n"
            "Open ⚙️ Settings to update the target channel if this is misconfigured."
        )

        if update.message and update.message.text and update.message.text.strip().startswith("/start"):
            await update.message.reply_text(msg)
            raise ApplicationHandlerStop()

        if _is_settings_escape(update):
            return await next_handler(update, context)

        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(msg)
        raise ApplicationHandlerStop()
