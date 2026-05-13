"""Register PTB handlers (webhook mode)."""

from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler, filters

from bot.handlers.callbacks import on_callback
from bot.handlers.channel_members import on_chat_member
from bot.handlers.messages_fsm import on_private_message
from bot.handlers.start import start_cmd


def register_handlers(application: Application) -> None:
    """
    Wire handlers.

    Notes:
    - Only `/start` uses a command; everything else is inline.
    - `ChatMemberHandler` requires the bot to be a **channel** administrator to receive member updates
      on the target public channel (subscriber list for optional DM broadcasts).
    """
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(m|bc|sch|lst|cfg|btn):"))
    application.add_handler(ChatMemberHandler(on_chat_member))
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_private_message),
    )
