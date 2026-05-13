"""Lightweight access checks (PTB v21 has no first-class middleware in all setups)."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config.settings import settings
from bot.database.session import get_session_factory
from bot.services.channel_service import user_can_manage_channel
from bot.services.settings_service import get_or_create_settings
from bot.handlers.prediction_admin import ST_PRED_MEDIA, ST_PRED_STICK, ST_PRED_TEXT
from bot.utils.fsm import ST_SET_CHANNEL, ST_SET_DISCUSSION, ST_SET_TZ, get_state

_SETTINGS_STATES = {ST_SET_CHANNEL, ST_SET_DISCUSSION, ST_SET_TZ}
_PRED_FSM_STATES = {ST_PRED_TEXT, ST_PRED_MEDIA, ST_PRED_STICK}


def _settings_escape_callback(data: str) -> bool:
    return data.startswith("cfg:") or data.startswith("pred:") or data in {"m:home", "m:cfg"}


async def ensure_dashboard_access(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    callback_data: str | None = None,
) -> tuple[bool, str | None]:
    """
    Return (allowed, denial_message).

    Non-admins are rejected. If a channel is configured, require post rights, but allow a
    small Settings escape hatch (mirrors `middlewares/admin_only.py`).
    """
    user = update.effective_user
    if not user or user.id not in settings.admin_id_set:
        return False, (
            "Not in ADMIN_TELEGRAM_IDS. Add your numeric Telegram user id on the VPS, "
            "then restart the bot service."
        )

    factory = get_session_factory()
    async with factory() as session:
        cfg = await get_or_create_settings(session)
        channel_id = cfg.target_channel_id

    if channel_id is None:
        return True, None

    ok = await user_can_manage_channel(context.bot, channel_id=channel_id, user_id=user.id)
    if ok:
        return True, None

    if callback_data and _settings_escape_callback(callback_data):
        return True, None

    if update.message:
        st = get_state(context.user_data)
        if st in _SETTINGS_STATES or st in _PRED_FSM_STATES:
            return True, None

    return False, (
        "You need admin + Post messages in the saved target channel; the bot must be "
        "admin there too. Fix channel under Settings if needed."
    )
