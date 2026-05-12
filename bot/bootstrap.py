"""Process bootstrap/shutdown for FastAPI + PTB webhook runtime."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram.ext import Application

from bot import models  # noqa: F401 — register ORM tables with metadata
from bot.config.settings import settings
from bot.database import Base
from bot.database.session import dispose_engine, get_engine, init_engine
from bot.handlers.register import register_handlers
from bot.runtime import set_application
from bot.scheduler.manager import BotScheduler
from bot.services.duckdns import update_duckdns
from bot.utils.logging_config import setup_logging

log = logging.getLogger(__name__)

_application: Application | None = None


async def init_bot_runtime() -> None:
    """Create DB schema, start PTB application, scheduler, and register Telegram webhook."""
    global _application

    setup_logging(settings.log_level)

    init_engine(settings.database_url, echo=False)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )
    register_handlers(app)
    set_application(app)

    await app.initialize()
    await app.start()

    app.bot_data["started_at"] = datetime.now(tz=timezone.utc)

    sch = BotScheduler.configure_singleton(timezone=settings.default_timezone)
    sch.start()
    await sch.reload_from_db()

    if settings.duckdns_domain and settings.duckdns_token:
        ok, body = await update_duckdns(settings.duckdns_domain, settings.duckdns_token)
        log.info("DuckDNS startup update: ok=%s body=%s", ok, body)

    await app.bot.set_webhook(
        url=settings.full_webhook_url,
        secret_token=settings.webhook_secret_token,
        allowed_updates=[
            "message",
            "edited_message",
            "callback_query",
            "chat_member",
            "my_chat_member",
        ],
    )
    log.info("Webhook set to %s", settings.full_webhook_url)

    _application = app


async def shutdown_bot_runtime() -> None:
    """Graceful shutdown for systemd restarts."""
    global _application

    mgr = BotScheduler.instance()
    if mgr:
        mgr.shutdown(wait=False)

    if _application is not None:
        try:
            await _application.bot.delete_webhook(drop_pending_updates=False)
        except Exception as e:
            log.info("delete_webhook failed: %s", e)
        await _application.stop()
        await _application.shutdown()
        _application = None

    await dispose_engine()
