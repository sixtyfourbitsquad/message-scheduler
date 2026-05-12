"""
Process-bound references to the running PTB `Application`.

APScheduler jobs run outside Telegram handlers and still need `application.bot`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from telegram.ext import Application


_application: Optional["Application"] = None


def set_application(app: "Application") -> None:
    global _application
    _application = app


def get_application() -> "Application":
    if _application is None:
        raise RuntimeError("Application not initialized")
    return _application
