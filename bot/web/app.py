"""FastAPI webhook receiver + health endpoints (reverse-proxy ready)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update

from bot.bootstrap import init_bot_runtime, shutdown_bot_runtime
from bot.config.settings import settings
from bot.runtime import get_application


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_bot_runtime()
    yield
    await shutdown_bot_runtime()


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Channel Automation Bot", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post(settings.webhook_path)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict:
        if x_telegram_bot_api_secret_token != settings.webhook_secret_token:
            raise HTTPException(status_code=401, detail="invalid secret token")

        data = await request.json()
        application = get_application()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}

    return app


app = create_app()
