"""Private-chat message router for multi-step wizards (FSM stored in `user_data`)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Message, Update
from telegram.ext import ContextTypes

from bot.database.session import get_session_factory
from bot.services.bot_user_service import record_bot_user_touch
from bot.handlers.helpers import esc
from bot.keyboards.inline import (
    kb_button_builder_controls,
    kb_schedule_preview,
    kb_settings_menu,
    kb_welcome_menu,
    kb_yes_no_skip,
)
from bot.models.schedule import ScheduleKind
from bot.services.settings_service import get_or_create_settings
from bot.services.welcome_service import get_or_create_welcome
from bot.utils.inline_keyboard_json import append_button_row, validate_http_url
from bot.utils.message_serialize import message_to_content_dict
from bot.utils import timezones as tzutil
from bot.utils.fsm import (
    ST_BC_BUTTON_TEXT,
    ST_BC_BUTTON_URL,
    ST_BC_WAIT_CONTENT,
    ST_SET_CHANNEL,
    ST_SET_DISCUSSION,
    ST_SET_TZ,
    ST_SCH_BUTTON_TEXT,
    ST_SCH_BUTTON_URL,
    ST_SCH_INTERVAL,
    ST_SCH_PREVIEW,
    ST_SCH_TIME,
    ST_SCH_WAIT_CONTENT,
    ST_SCH_WEEKDAY,
    ST_WEL_BTN_TEXT,
    ST_WEL_BTN_URL,
    ST_WEL_DELETE_AFTER,
    ST_WEL_WAIT_CONTENT,
    get_data,
    get_state,
    set_state,
)

log = logging.getLogger(__name__)


async def _edit_panel(context: ContextTypes.DEFAULT_TYPE, user_data: dict, *, text: str, reply_markup=None) -> None:
    chat_id = user_data.get("panel_chat_id")
    mid = user_data.get("panel_message_id")
    if not chat_id or not mid:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=mid,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception as e:
        log.info("panel edit failed: %s", e)


def _resolve_forwarded_chat_id(msg: Message) -> int | None:
    """Best-effort extraction of a forwarded channel/group chat id."""
    origin = msg.forward_origin
    if not origin:
        return None
    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if chat:
        return int(chat.id)
    return None


async def on_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    from bot.handlers.gates import ensure_dashboard_access

    allowed, denial = await ensure_dashboard_access(update, context)
    if not allowed:
        await update.message.reply_text(f"⛔ {denial or 'Not allowed.'}")
        return

    u = update.effective_user
    if u:
        async with get_session_factory()() as session:
            await record_bot_user_touch(session, u)
            await session.commit()

    msg = update.message
    ud = context.user_data
    st = get_state(ud)

    from bot.handlers.prediction_admin import ST_PRED_MEDIA, ST_PRED_STICK, ST_PRED_TEXT, handle_prediction_admin_message

    if st in (ST_PRED_TEXT, ST_PRED_MEDIA, ST_PRED_STICK):
        if await handle_prediction_admin_message(update, context):
            return

    if st in {ST_BC_BUTTON_URL, ST_SCH_BUTTON_URL, ST_WEL_BTN_URL}:
        await _capture_button_url(update, context)
        return

    if st == ST_SET_CHANNEL:
        await _capture_channel(update, context)
        return
    if st == ST_SET_DISCUSSION:
        await _capture_discussion(update, context)
        return
    if st == ST_SET_TZ:
        await _capture_tz(update, context)
        return

    if st == ST_BC_WAIT_CONTENT:
        payload = message_to_content_dict(msg)
        if payload.get("type") == "unsupported":
            await msg.reply_text(payload.get("hint", "Unsupported message."))
            return
        get_data(ud)["content"] = payload
        from bot.utils.fsm import ST_BC_BUTTONS_ASK

        set_state(ud, ST_BC_BUTTONS_ASK)
        await _edit_panel(
            context,
            ud,
            text="<b>STEP 2/4 — Inline buttons</b>\n\nDo you want URL buttons under the post?",
            reply_markup=kb_yes_no_skip(yes_data="bc:btny", no_data="bc:btnn", cancel_data="bc:cancel"),
        )
        return

    if st == ST_BC_BUTTON_TEXT:
        label = (msg.text or "").strip()
        if not label:
            await msg.reply_text("Please send non-empty button text.")
            return
        get_data(ud)["pending_btn_text"] = label
        set_state(ud, ST_BC_BUTTON_URL)
        await msg.reply_text("Now send the button URL (must start with http/https).")
        return

    if st == ST_SCH_WAIT_CONTENT:
        payload = message_to_content_dict(msg)
        if payload.get("type") == "unsupported":
            await msg.reply_text(payload.get("hint", "Unsupported message."))
            return
        get_data(ud)["content"] = payload
        from bot.utils.fsm import ST_SCH_BUTTONS_ASK

        set_state(ud, ST_SCH_BUTTONS_ASK)
        await _edit_panel(
            context,
            ud,
            text="<b>Scheduler — STEP 2</b>\n\nAdd inline URL buttons?",
            reply_markup=kb_yes_no_skip(yes_data="sch:ab:y", no_data="sch:ab:n", cancel_data="sch:cancel"),
        )
        return

    if st == ST_SCH_BUTTON_TEXT:
        label = (msg.text or "").strip()
        if not label:
            await msg.reply_text("Please send non-empty button text.")
            return
        get_data(ud)["pending_btn_text"] = label
        set_state(ud, ST_SCH_BUTTON_URL)
        await msg.reply_text("Now send the button URL (must start with http/https).")
        return

    if st == ST_SCH_WEEKDAY:
        m = re.fullmatch(r"(\d)", (msg.text or "").strip())
        if not m:
            await msg.reply_text("Send a single digit 0-6 where 0=Monday.")
            return
        wd = int(m.group(1))
        if wd < 0 or wd > 6:
            await msg.reply_text("Out of range.")
            return
        get_data(ud)["sch_weekday"] = wd
        set_state(ud, ST_SCH_TIME)
        await msg.reply_text("Now send time as HH:MM (24h).")
        return

    if st == ST_SCH_TIME:
        await _capture_sch_time(update, context)
        return

    if st == ST_SCH_INTERVAL:
        s = (msg.text or "").strip()
        if not s.isdigit() or int(s) <= 0:
            await msg.reply_text("Send a positive integer (seconds).")
            return
        get_data(ud)["sch_interval_s"] = int(s)
        set_state(ud, ST_SCH_PREVIEW)
        await _render_sch_preview_panel(update, context)
        return

    if st == ST_WEL_WAIT_CONTENT:
        payload = message_to_content_dict(msg)
        if payload.get("type") == "unsupported":
            await msg.reply_text(payload.get("hint", "Unsupported message."))
            return
        async with get_session_factory()() as session:
            w = await get_or_create_welcome(session)
            w.content_json = payload
            w.text = None
            w.media_json = None
            await session.commit()
        set_state(ud, None)
        await msg.reply_text(
            "✅ Welcome #1 saved. Add URL buttons from the Welcome menu if you want; "
            "those buttons are used for join DMs, test-to-channel, and test-to-you.",
            reply_markup=kb_welcome_menu(),
        )
        return

    if st == ST_WEL_BTN_TEXT:
        label = (msg.text or "").strip()
        if not label:
            await msg.reply_text("Please send non-empty button text.")
            return
        get_data(ud)["pending_btn_text"] = label
        set_state(ud, ST_WEL_BTN_URL)
        await msg.reply_text("Now send the button URL (must start with http/https).")
        return

    if st == ST_WEL_DELETE_AFTER:
        s = (msg.text or "").strip()
        if not s.isdigit():
            await msg.reply_text("Send an integer (seconds).")
            return
        secs = int(s)
        async with get_session_factory()() as session:
            w = await get_or_create_welcome(session)
            w.delete_after_seconds = None if secs == 0 else secs
            await session.commit()
        set_state(ud, None)
        await msg.reply_text("✅ Auto-delete updated.", reply_markup=kb_welcome_menu())
        return


async def _capture_button_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    ud = context.user_data
    st = get_state(ud)

    url = (msg.text or "").strip()
    if not validate_http_url(url):
        await msg.reply_text("Invalid URL. Must start with http:// or https://")
        return

    label = get_data(ud).get("pending_btn_text") or "Link"
    rows = get_data(ud).setdefault("buttons", [])
    if not isinstance(rows, list):
        rows = []
        get_data(ud)["buttons"] = rows
    new_row = bool(get_data(ud).get("btn_newrow", True))
    append_button_row(rows, text=label, url=url, new_row=new_row)
    get_data(ud)["btn_newrow"] = False

    if st == ST_BC_BUTTON_URL:
        set_state(ud, ST_BC_BUTTON_TEXT)
    elif st == ST_SCH_BUTTON_URL:
        set_state(ud, ST_SCH_BUTTON_TEXT)
    elif st == ST_WEL_BTN_URL:
        set_state(ud, ST_WEL_BTN_TEXT)

    await msg.reply_text("Button added. Send another label, or press Done.", reply_markup=kb_button_builder_controls())


async def _capture_sch_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    ud = context.user_data
    d = get_data(ud)
    kind = d.get("sch_kind")

    async with get_session_factory()() as session:
        cfg = await get_or_create_settings(session)
        tz = cfg.timezone or "UTC"

    now_utc = datetime.now(tz=timezone.utc)

    if kind == ScheduleKind.once.value:
        raw = (msg.text or "").strip()
        try:
            dt_local = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            dt_utc = dt_local.replace(tzinfo=ZoneInfo(tz)).astimezone(ZoneInfo("UTC"))
        except Exception:
            await msg.reply_text("Format must be YYYY-MM-DD HH:MM")
            return
        d["sch_next_utc"] = dt_utc
        set_state(ud, ST_SCH_PREVIEW)
        await _render_sch_preview_panel(update, context)
        return

    if kind in (ScheduleKind.daily.value, ScheduleKind.weekly.value):
        raw = (msg.text or "").strip()
        if not re.fullmatch(r"\d{1,2}:\d{2}", raw):
            await msg.reply_text("Format must be HH:MM (24h).")
            return
        d["sch_hhmm"] = raw
        if kind == ScheduleKind.daily.value:
            d.pop("daily_slot_times", None)
            d.pop("sch_tz_override", None)
            d.pop("sch_jitter", None)
            d["sch_next_utc"] = tzutil.next_daily_at(raw, tz, after=now_utc)
        else:
            wd = int(d.get("sch_weekday"))
            d["sch_next_utc"] = tzutil.next_weekday_at(raw, wd, tz, after=now_utc)
        set_state(ud, ST_SCH_PREVIEW)
        await _render_sch_preview_panel(update, context)
        return


async def _render_sch_preview_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = context.user_data
    d = get_data(ud)
    content = d.get("content") or {}
    if not d.get("sch_title"):
        if content.get("type") == "text":
            d["sch_title"] = (content.get("text") or "Scheduled post")[:120]
        elif content.get("caption"):
            d["sch_title"] = (content.get("caption") or "Scheduled post")[:120]
        else:
            d["sch_title"] = "Scheduled post"

    summary = (
        f"<b>Scheduler — Preview</b>\n\n"
        f"Title: <code>{esc(str(d.get('sch_title')))}</code>\n"
        f"Kind: <code>{esc(str(d.get('sch_kind')))}</code>\n"
    )
    if d.get("daily_slot_times"):
        summary += (
            f"Daily slots (local): <code>{esc(str(d.get('daily_slot_times')))}</code>\n"
            f"Timezone: <code>{esc(str(d.get('sch_tz_override') or 'from Settings'))}</code>\n"
        )
    if d.get("sch_jitter") is not None:
        summary += f"Jitter max: <code>{esc(str(d.get('sch_jitter')))}</code>s\n"
    if isinstance(d.get("content_pool_json"), list) and d["content_pool_json"]:
        summary += f"Content pool: <code>{len(d['content_pool_json'])}</code> variants (random per run)\n"
    summary += (
        f"Next run (UTC): <code>{esc(str(d.get('sch_next_utc')))}</code>\n"
        f"Interval seconds: <code>{esc(str(d.get('sch_interval_s')))}</code>\n"
    )
    await _edit_panel(context, ud, text=summary, reply_markup=kb_schedule_preview())


async def _capture_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    ud = context.user_data
    channel_id = _resolve_forwarded_chat_id(msg)
    if channel_id is None:
        t = (msg.text or "").strip()
        try:
            chat = await context.bot.get_chat(t)
            channel_id = int(chat.id)
        except Exception:
            channel_id = None
    if channel_id is None:
        await msg.reply_text("Could not resolve channel. Forward a channel message or send @username / id.")
        return
    async with get_session_factory()() as session:
        s = await get_or_create_settings(session)
        s.target_channel_id = int(channel_id)
        await session.commit()
    set_state(ud, None)
    await msg.reply_text("✅ Target channel saved.", reply_markup=kb_settings_menu())


async def _capture_discussion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    ud = context.user_data
    gid = _resolve_forwarded_chat_id(msg)
    if gid is None:
        t = (msg.text or "").strip()
        if t.lstrip("-").isdigit():
            gid = int(t)
    if gid is None:
        await msg.reply_text("Forward a group message or send numeric chat id.")
        return
    async with get_session_factory()() as session:
        s = await get_or_create_settings(session)
        s.discussion_group_id = int(gid)
        await session.commit()
    set_state(ud, None)
    await msg.reply_text("✅ Discussion group saved.", reply_markup=kb_settings_menu())


async def _capture_tz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    ud = context.user_data
    tz = (msg.text or "").strip()
    try:
        ZoneInfo(tz)
    except Exception:
        await msg.reply_text("Unknown timezone. Example: Europe/Berlin")
        return
    async with get_session_factory()() as session:
        s = await get_or_create_settings(session)
        s.timezone = tz
        await session.commit()
    set_state(ud, None)
    await msg.reply_text("✅ Timezone saved.", reply_markup=kb_settings_menu())
