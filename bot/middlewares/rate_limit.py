"""Very small per-user rate limiter to protect against accidental double-taps / loops."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


class SimpleRateLimitMiddleware:
    """Monotonic per-user throttle for callbacks + private messages."""

    def __init__(self, *, min_interval_s: float = 0.35) -> None:
        self.min_interval_s = min_interval_s
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        next_handler: Handler,
    ) -> Any:
        user = update.effective_user
        if user is None:
            return await next_handler(update, context)

        if not (update.callback_query or update.message):
            return await next_handler(update, context)

        now = time.monotonic()
        last = self._last.get(user.id, 0.0)
        if now - last < self.min_interval_s:
            if update.callback_query:
                await update.callback_query.answer()
            raise ApplicationHandlerStop()

        self._last[user.id] = now
        return await next_handler(update, context)
