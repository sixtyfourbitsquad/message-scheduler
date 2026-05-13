"""Callback-query router: inline-only navigation + wizard steps."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import delete, select, text
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.database.session import get_session_factory
from bot.handlers.helpers import DASHBOARD_HTML, edit_or_send, esc
from bot.keyboards.inline import (
    kb_broadcast_entry,
    kb_broadcast_preview,
    kb_button_builder_controls,
    kb_confirm_delete,
    kb_main_menu,
    kb_posts_row,
    kb_schedule_kind,
    kb_schedule_preview,
    kb_scheduler_entry,
    kb_settings_menu,
    kb_stats_refresh,
    kb_welcome_menu,
)
from bot.models.broadcast_log import BroadcastLog
from bot.models.schedule import Schedule, ScheduleKind
from bot.scheduler.manager import BotScheduler
from bot.services.broadcast_fanout_service import fanout_dm_to_subscribers
from bot.services.channel_delivery_service import record_channel_delivery
from bot.services.channel_subscriber_service import list_active_subscriber_ids
from bot.services.content_poster import send_content_to_chat
from bot.services.settings_service import get_or_create_settings
from bot.services.stats_service import stats_snapshot
from bot.services.welcome_service import effective_welcome_content, get_or_create_welcome
from bot.utils import timezones as tzutil
from bot.utils.fsm import (
    ST_BC_BUTTON_TEXT,
    ST_BC_BUTTON_URL,
    ST_BC_PREVIEW,
    ST_BC_WAIT_CONTENT,
    ST_SET_CHANNEL,
    ST_SET_DISCUSSION,
    ST_SET_TZ,
    ST_SCH_BUTTON_TEXT,
    ST_SCH_BUTTON_URL,
    ST_SCH_INTERVAL,
    ST_SCH_KIND,
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
    reset_fsm,
    set_state,
)

log = logging.getLogger(__name__)

_MAX_SCHED_JITTER_S = 600


def _remember_panel_message(message, user_data: dict) -> None:
    user_data["panel_chat_id"] = message.chat_id
    user_data["panel_message_id"] = message.message_id


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data:
        return

    from bot.handlers.gates import ensure_dashboard_access

    allowed, denial = await ensure_dashboard_access(update, context, callback_data=q.data)
    if not allowed:
        await q.answer(f"⛔ {denial or 'Not allowed.'}", show_alert=True)
        return

    await q.answer()
    data = q.data

    # ---- Root menu ----
    if data == "m:home":
        reset_fsm(context.user_data)
        await edit_or_send(update, context, text=DASHBOARD_HTML, reply_markup=kb_main_menu())
        return

    if data == "m:x":
        try:
            await q.message.delete()
        except Exception:
            await q.message.edit_text("✅ Closed. Send /start to reopen.")
        return

    if data == "m:bc":
        reset_fsm(context.user_data)
        await edit_or_send(
            update,
            context,
            text="<b>📢 Broadcast</b>\n\nCreate a post and send it to your public channel.",
            reply_markup=kb_broadcast_entry(),
        )
        return

    if data == "m:sch":
        reset_fsm(context.user_data)
        await edit_or_send(
            update,
            context,
            text="<b>⏰ Scheduler</b>\n\nAutomate recurring or one-time channel posts.",
            reply_markup=kb_scheduler_entry(),
        )
        return

    if data == "m:lst":
        await _render_schedule_list(update, context)
        return

    if data == "m:wel":
        await _render_welcome_menu(update, context)
        return

    if data == "m:cfg":
        await _render_settings(update, context)
        return

    if data == "m:st":
        await _render_stats(update, context)
        return

    # ---- Broadcast wizard ----
    if data == "bc:start":
        reset_fsm(context.user_data)
        set_state(context.user_data, ST_BC_WAIT_CONTENT)
        get_data(context.user_data).clear()
        get_data(context.user_data)["btn_ctx"] = "bc"
        m = await edit_or_send(
            update,
            context,
            text=(
                "<b>STEP 1/4 — Content</b>\n\n"
                "Send <b>one</b> message with your post content.\n"
                "Supported: text, photo, video, GIF, document, audio, voice (+ captions).\n\n"
                "<i>Tip:</i> captions and text formatting are preserved when possible."
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="bc:cancel")]]),
        )
        _remember_panel_message(m, context.user_data)
        return

    if data == "bc:cancel":
        reset_fsm(context.user_data)
        await edit_or_send(update, context, text=DASHBOARD_HTML, reply_markup=kb_main_menu())
        return

    if data == "bc:btny":
        set_state(context.user_data, ST_BC_BUTTON_TEXT)
        d = get_data(context.user_data)
        d["btn_ctx"] = "bc"
        d["buttons"] = []
        d["btn_newrow"] = True
        await edit_or_send(
            update,
            context,
            text="<b>STEP 2/4 — Buttons</b>\n\nSend the <b>button label</b> (plain text).",
            reply_markup=kb_button_builder_controls(),
        )
        return

    if data == "bc:btnn":
        set_state(context.user_data, ST_BC_PREVIEW)
        d = get_data(context.user_data)
        d.setdefault("buttons", None)
        await _render_bc_preview(update, context)
        return

    if data == "bc:send" or data.startswith("bc:send:"):
        mode = "ch"
        if data == "bc:send:both":
            mode = "both"
        elif data == "bc:send:dm":
            mode = "dm"
        await _broadcast_send_now(update, context, delivery=mode)
        return

    if data == "bc:queue_sch":
        # Move current broadcast payload into scheduler draft
        d = get_data(context.user_data)
        content = d.get("content")
        buttons = d.get("buttons")
        reset_fsm(context.user_data)
        nd = get_data(context.user_data)
        nd["content"] = content
        nd["buttons"] = buttons
        nd["btn_ctx"] = "sch"
        set_state(context.user_data, ST_SCH_KIND)
        m = await edit_or_send(
            update,
            context,
            text="<b>⏰ Schedule this post</b>\n\nChoose schedule type:",
            reply_markup=kb_schedule_kind(),
        )
        _remember_panel_message(m, context.user_data)
        return

    # ---- Scheduler wizard ----
    if data == "sch:start":
        reset_fsm(context.user_data)
        get_data(context.user_data).clear()
        get_data(context.user_data)["btn_ctx"] = "sch"
        set_state(context.user_data, ST_SCH_WAIT_CONTENT)
        m = await edit_or_send(
            update,
            context,
            text="<b>Scheduler — STEP 1</b>\n\nSend the post content (one message).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")]]),
        )
        _remember_panel_message(m, context.user_data)
        return

    if data == "sch:cancel":
        reset_fsm(context.user_data)
        await edit_or_send(update, context, text=DASHBOARD_HTML, reply_markup=kb_main_menu())
        return

    if data == "sch:ab:y":
        set_state(context.user_data, ST_SCH_BUTTON_TEXT)
        d = get_data(context.user_data)
        d["btn_ctx"] = "sch"
        d["buttons"] = []
        d["btn_newrow"] = True
        m = await edit_or_send(
            update,
            context,
            text="<b>Scheduler — Buttons</b>\n\nSend the <b>button label</b> (plain text).",
            reply_markup=kb_button_builder_controls(),
        )
        _remember_panel_message(m, context.user_data)
        return

    if data == "sch:ab:n":
        get_data(context.user_data)["buttons"] = None
        set_state(context.user_data, ST_SCH_KIND)
        m = await edit_or_send(
            update,
            context,
            text="<b>Scheduler — STEP 3</b>\n\nChoose schedule type:",
            reply_markup=kb_schedule_kind(),
        )
        _remember_panel_message(m, context.user_data)
        return

    if data == "sch:k:daily_peak":
        d = get_data(context.user_data)
        d["sch_kind"] = ScheduleKind.daily.value
        d["daily_slot_times"] = ["10:00", "14:00", "16:00", "18:00", "21:00", "23:00"]
        d["sch_tz_override"] = "Asia/Kolkata"
        d["sch_jitter"] = 90
        d["sch_hhmm"] = None
        now_utc = datetime.now(tz=timezone.utc)
        d["sch_next_utc"] = tzutil.next_daily_multi_slots_at(
            d["daily_slot_times"], "Asia/Kolkata", after=now_utc
        )
        set_state(context.user_data, ST_SCH_PREVIEW)
        from bot.handlers.messages_fsm import _render_sch_preview_panel

        await _render_sch_preview_panel(update, context)
        return

    if data.startswith("sch:k:"):
        kind = data.split(":", 2)[2]
        d = get_data(context.user_data)
        d["sch_kind"] = kind
        d.pop("daily_slot_times", None)
        d.pop("sch_tz_override", None)
        d.pop("sch_jitter", None)
        await _prompt_time_for_selected_kind(update, context)
        return

    if data == "sch:save":
        await _schedule_save(update, context)
        return

    # ---- Button builder (shared) ----
    if data == "btn:newrow":
        get_data(context.user_data)["btn_newrow"] = True
        return

    if data == "btn:done":
        st = get_state(context.user_data)
        ctx = get_data(context.user_data).get("btn_ctx")
        if ctx == "bc" and st in {ST_BC_BUTTON_TEXT, ST_BC_BUTTON_URL}:
            set_state(context.user_data, ST_BC_PREVIEW)
            await _render_bc_preview(update, context)
            return
        if ctx == "sch" and st in {ST_SCH_BUTTON_TEXT, ST_SCH_BUTTON_URL}:
            set_state(context.user_data, ST_SCH_KIND)
            m = await edit_or_send(
                update,
                context,
                text="<b>Scheduler — STEP 3</b>\n\nChoose schedule type:",
                reply_markup=kb_schedule_kind(),
            )
            _remember_panel_message(m, context.user_data)
            return
        if ctx == "wel" and st in {ST_WEL_BTN_TEXT, ST_WEL_BTN_URL}:
            async with get_session_factory()() as session:
                w = await get_or_create_welcome(session)
                w.buttons_json = get_data(context.user_data).get("buttons") or None
                await session.commit()
            reset_fsm(context.user_data)
            await _render_welcome_menu(update, context)
            return
        return

    if data == "btn:cancel":
        reset_fsm(context.user_data)
        await edit_or_send(update, context, text=DASHBOARD_HTML, reply_markup=kb_main_menu())
        return

    # ---- Scheduled posts list actions ----
    if data.startswith("lst:v:"):
        sid = int(data.split(":")[2])
        await _render_schedule_detail(update, context, sid)
        return
    if data.startswith("lst:e:"):
        sid = int(data.split(":")[2])
        await _begin_schedule_edit(update, context, sid)
        return
    if data.startswith("lst:p:"):
        sid = int(data.split(":")[2])
        await _pause_schedule(update, context, sid, paused=True)
        return
    if data.startswith("lst:r:"):
        sid = int(data.split(":")[2])
        await _pause_schedule(update, context, sid, paused=False)
        return
    if data.startswith("lst:d:"):
        sid = int(data.split(":")[2])
        await edit_or_send(
            update,
            context,
            text=f"<b>Delete schedule #{sid}?</b>",
            reply_markup=kb_confirm_delete(sid),
        )
        return
    if data.startswith("lst:dd:"):
        sid = int(data.split(":")[2])
        await _delete_schedule(update, context, sid)
        return

    # ---- Welcome ----
    if data == "wel:toggle":
        factory = get_session_factory()
        async with factory() as session:
            w = await get_or_create_welcome(session)
            w.enabled = not bool(w.enabled)
            await session.commit()
        await _render_welcome_menu(update, context)
        return
    if data == "wel:set":
        set_state(context.user_data, ST_WEL_WAIT_CONTENT)
        await edit_or_send(
            update,
            context,
            text=(
                "<b>Set welcome message #1</b>\n\n"
                "<b>Forward</b> one message here, or send the same kind of message directly.\n"
                "Supported: text, photo/video/GIF with caption, document, audio, voice.\n\n"
                "<i>Tip:</i> formatting and captions are kept when possible."
            ),
            reply_markup=kb_welcome_menu(),
        )
        return
    if data == "wel:dm":
        user = update.effective_user
        if not user:
            return
        factory = get_session_factory()
        async with factory() as session:
            w = await get_or_create_welcome(session)
            content = effective_welcome_content(w)
            buttons = w.buttons_json
        if not content:
            await edit_or_send(
                update,
                context,
                text="❌ No welcome content yet. Use <b>Set welcome #1</b> first.",
                reply_markup=kb_welcome_menu(),
            )
            return
        try:
            mid = await send_content_to_chat(
                context.bot, chat_id=user.id, content=content, buttons_json=buttons
            )
            if mid:
                await edit_or_send(
                    update,
                    context,
                    text="✅ Sent a copy to your private chat with the bot (with buttons if configured).",
                    reply_markup=kb_welcome_menu(),
                )
            else:
                await edit_or_send(
                    update,
                    context,
                    text="❌ Could not send (unsupported content?).",
                    reply_markup=kb_welcome_menu(),
                )
        except Exception as e:
            await edit_or_send(
                update,
                context,
                text=f"❌ Send failed:\n<pre>{esc(repr(e))}</pre>",
                reply_markup=kb_welcome_menu(),
            )
        return
    if data == "wel:ch":
        factory = get_session_factory()
        async with factory() as session:
            cfg = await get_or_create_settings(session)
            channel_id = cfg.target_channel_id
            w = await get_or_create_welcome(session)
            content = effective_welcome_content(w)
            buttons = w.buttons_json
        if not channel_id:
            await edit_or_send(
                update,
                context,
                text="❌ Set target channel in ⚙️ Settings first.",
                reply_markup=kb_welcome_menu(),
            )
            return
        if not content:
            await edit_or_send(
                update,
                context,
                text="❌ No welcome content yet. Use <b>Set welcome #1</b> first.",
                reply_markup=kb_welcome_menu(),
            )
            return
        try:
            mid = await send_content_to_chat(
                context.bot, chat_id=channel_id, content=content, buttons_json=buttons
            )
            if mid:
                async with get_session_factory()() as session:
                    await record_channel_delivery(
                        session,
                        channel_id=int(channel_id),
                        kind="welcome_test",
                        admin_id=update.effective_user.id if update.effective_user else None,
                    )
                    await session.commit()
                await edit_or_send(
                    update,
                    context,
                    text="✅ Posted a copy to your target channel (with buttons if configured).",
                    reply_markup=kb_welcome_menu(),
                )
            else:
                await edit_or_send(
                    update,
                    context,
                    text="❌ Could not post (unsupported content?).",
                    reply_markup=kb_welcome_menu(),
                )
        except Exception as e:
            await edit_or_send(
                update,
                context,
                text=f"❌ Post failed:\n<pre>{esc(repr(e))}</pre>",
                reply_markup=kb_welcome_menu(),
            )
        return
    if data == "wel:btn":
        d = get_data(context.user_data)
        d["btn_ctx"] = "wel"
        async with get_session_factory()() as session:
            w = await get_or_create_welcome(session)
            existing = w.buttons_json
        d["buttons"] = deepcopy(existing) if existing else []
        d["btn_newrow"] = True
        set_state(context.user_data, ST_WEL_BTN_TEXT)
        await edit_or_send(
            update,
            context,
            text=(
                "<b>URL buttons</b> under the welcome (used for join DMs, test-to-channel, "
                "and test-to-you).\n\n"
                "<b>1.</b> Send the button text.\n"
                "<b>2.</b> Send the link (<code>https://…</code>).\n"
                "Repeat for more buttons, then tap <b>Done</b>."
            ),
            reply_markup=kb_button_builder_controls(),
        )
        return
    if data == "wel:del":
        set_state(context.user_data, ST_WEL_DELETE_AFTER)
        await edit_or_send(
            update,
            context,
            text="Send auto-delete seconds as an integer (e.g. <code>30</code>), or <code>0</code> to disable.",
            reply_markup=kb_welcome_menu(),
        )
        return

    # ---- Settings ----
    if data == "cfg:ch":
        set_state(context.user_data, ST_SET_CHANNEL)
        await edit_or_send(
            update,
            context,
            text=(
                "<b>Set target channel</b>\n\n"
                "Forward any message from the channel to this chat, "
                "or send the channel username like <code>@mychannel</code> / numeric id <code>-100...</code>."
            ),
            reply_markup=kb_settings_menu(),
        )
        return
    if data == "cfg:dg":
        set_state(context.user_data, ST_SET_DISCUSSION)
        await edit_or_send(
            update,
            context,
            text=(
                "<b>Set discussion group</b> (optional)\n\n"
                "Forward a message from a linked supergroup or send its chat id, if you use one."
            ),
            reply_markup=kb_settings_menu(),
        )
        return
    if data == "cfg:tz":
        set_state(context.user_data, ST_SET_TZ)
        await edit_or_send(
            update,
            context,
            text="Send an IANA timezone, e.g. <code>Asia/Kolkata</code> (India) or <code>UTC</code>.",
            reply_markup=kb_settings_menu(),
        )
        return
    if data == "cfg:log":
        factory = get_session_factory()
        async with factory() as session:
            s = await get_or_create_settings(session)
            s.logs_enabled = not bool(s.logs_enabled)
            await session.commit()
        await _render_settings(update, context)
        return
    if data == "cfg:status":
        me = await context.bot.get_me()
        await edit_or_send(
            update,
            context,
            text=f"<b>Bot status</b>\n\n<code>@{esc(me.username)}</code>\nBot id: <code>{me.id}</code>",
            reply_markup=kb_settings_menu(),
        )
        return
    if data == "cfg:rsch":
        mgr = BotScheduler.instance()
        if mgr:
            await mgr.reload_from_db()
        await edit_or_send(
            update,
            context,
            text="✅ Scheduler jobs reloaded from PostgreSQL.",
            reply_markup=kb_settings_menu(),
        )
        return
    if data == "cfg:db":
        ok = True
        try:
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as e:
            ok = False
            err = repr(e)
        if ok:
            txt = "✅ Database connection healthy."
        else:
            txt = f"❌ Database check failed:\n<pre>{esc(err)}</pre>"
        await edit_or_send(update, context, text=txt, reply_markup=kb_settings_menu())
        return


async def _render_bc_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = get_data(context.user_data)
    content = d.get("content") or {}
    ctype = content.get("type", "?")
    preview = (
        f"<b>STEP 3/4 — Preview</b>\n\n"
        f"Type: <code>{esc(str(ctype))}</code>\n"
        "<i>Choose: channel only, channel + subscriber DMs, or subscribers only.</i>\n"
    )
    if content.get("type") == "text":
        preview += f"\n{esc(content.get('text','')[:3500])}"
    elif content.get("caption"):
        preview += f"\nCaption:\n{esc(content.get('caption','')[:3500])}"
    await edit_or_send(update, context, text=preview, reply_markup=kb_broadcast_preview())


async def _broadcast_send_now(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, delivery: str = "ch"
) -> None:
    """delivery: ch | both | dm — channel post, optional subscriber fan-out in private."""
    factory = get_session_factory()
    admin_id = update.effective_user.id if update.effective_user else None
    subscriber_ids: list[int] = []

    async with factory() as session:
        cfg = await get_or_create_settings(session)
        channel_id = cfg.target_channel_id
        if not channel_id:
            await edit_or_send(
                update,
                context,
                text="❌ Set target channel in ⚙️ Settings first.",
                reply_markup=kb_main_menu(),
            )
            return

        d = get_data(context.user_data)
        content = d.get("content") or {}
        buttons = d.get("buttons")

        if delivery in ("both", "dm"):
            subscriber_ids = await list_active_subscriber_ids(session)

    ch_mid: int | None = None
    dm_ok, dm_fail = 0, 0

    try:
        if delivery in ("ch", "both"):
            ch_mid = await send_content_to_chat(
                context.bot, chat_id=int(channel_id), content=content, buttons_json=buttons
            )
            if not ch_mid:
                await edit_or_send(
                    update,
                    context,
                    text="❌ Unsupported content for channel.",
                    reply_markup=kb_main_menu(),
                )
                return

        if delivery == "dm":
            if not subscriber_ids:
                await edit_or_send(
                    update,
                    context,
                    text=(
                        "❌ No subscribers in the list yet.\n\n"
                        "People are added when they <b>join your channel</b> (bot must be channel admin). "
                        "They still must <b>/start</b> this bot before any DM can be delivered."
                    ),
                    reply_markup=kb_main_menu(),
                )
                return
            dm_ok, dm_fail = await fanout_dm_to_subscribers(
                context.bot,
                user_ids=subscriber_ids,
                content=content,
                buttons_json=buttons,
                channel_id=int(channel_id),
                admin_id=admin_id,
            )
            async with factory() as session:
                session.add(
                    BroadcastLog(
                        admin_id=admin_id,
                        channel_id=int(channel_id),
                        status="sent",
                        payload_summary=str(content.get("type")),
                        meta={
                            "delivery": "dm",
                            "subscriber_dm_ok": dm_ok,
                            "subscriber_dm_fail": dm_fail,
                            "subscriber_targets": len(subscriber_ids),
                        },
                    )
                )
                await session.commit()
            reset_fsm(context.user_data)
            await edit_or_send(
                update,
                context,
                text=(
                    f"✅ Subscriber broadcast done.\n"
                    f"DM ok: <code>{dm_ok}</code> · failed / blocked: <code>{dm_fail}</code> · "
                    f"list size: <code>{len(subscriber_ids)}</code>"
                ),
                reply_markup=kb_main_menu(),
            )
            return

        if delivery == "both":
            dm_ok, dm_fail = await fanout_dm_to_subscribers(
                context.bot,
                user_ids=subscriber_ids,
                content=content,
                buttons_json=buttons,
                channel_id=int(channel_id),
                admin_id=admin_id,
            )

        async with factory() as session:
            session.add(
                BroadcastLog(
                    admin_id=admin_id,
                    channel_id=int(channel_id),
                    status="sent",
                    payload_summary=str(content.get("type")),
                    meta={
                        "delivery": delivery,
                        "subscriber_dm_ok": dm_ok if delivery == "both" else 0,
                        "subscriber_dm_fail": dm_fail if delivery == "both" else 0,
                        "subscriber_targets": len(subscriber_ids) if delivery == "both" else 0,
                    },
                )
            )
            await record_channel_delivery(
                session,
                channel_id=int(channel_id),
                kind="broadcast",
                admin_id=admin_id,
            )
            await session.commit()

        reset_fsm(context.user_data)
        if delivery == "both":
            msg = (
                f"✅ Channel post sent and subscriber DMs finished.\n"
                f"DM ok: <code>{dm_ok}</code> · failed / blocked: <code>{dm_fail}</code> · "
                f"list size: <code>{len(subscriber_ids)}</code>"
            )
        else:
            msg = "✅ Broadcast sent to channel."
        await edit_or_send(update, context, text=msg, reply_markup=kb_main_menu())

    except Exception as e:
        log.exception("broadcast failed: %s", e)
        await edit_or_send(
            update,
            context,
            text=f"❌ Send failed:\n<pre>{esc(repr(e))}</pre>",
            reply_markup=kb_main_menu(),
        )


async def _prompt_time_for_selected_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """After schedule kind is chosen, ask the admin for the timing details (via private messages)."""
    d = get_data(context.user_data)
    kind = d.get("sch_kind")
    set_state(context.user_data, ST_SCH_TIME)
    if kind == ScheduleKind.once.value:
        await edit_or_send(
            update,
            context,
            text=(
                "<b>One-time schedule</b>\n\n"
                "Send local date/time as:\n<code>YYYY-MM-DD HH:MM</code>\n\n"
                "Timezone uses your Settings timezone."
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")]]),
        )
        return
    if kind in (ScheduleKind.daily.value, ScheduleKind.weekly.value):
        if kind == ScheduleKind.weekly.value:
            set_state(context.user_data, ST_SCH_WEEKDAY)
            await edit_or_send(
                update,
                context,
                text="Weekly: send weekday number <code>0-6</code> where <code>0=Monday</code>.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")]]),
            )
            return
        await edit_or_send(
            update,
            context,
            text="Daily: send time as <code>HH:MM</code> (24h, local time in your Settings timezone).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")]]),
        )
        return
    if kind == ScheduleKind.interval.value:
        set_state(context.user_data, ST_SCH_INTERVAL)
        await edit_or_send(
            update,
            context,
            text="Interval: send repeat interval in <b>seconds</b> (integer).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")]]),
        )
        return


async def _schedule_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    d = get_data(context.user_data)
    async with factory() as session:
        cfg = await get_or_create_settings(session)
        tz = d.get("sch_tz_override") or cfg.timezone or "Asia/Kolkata"

        sch_kind = d.get("sch_kind")
        title = (d.get("sch_title") or "Scheduled post")[:250]
        content = d.get("content") or {}
        buttons = d.get("buttons")

        row = Schedule(
            title=title,
            kind=sch_kind,
            timezone=tz,
            content_json=content,
            buttons_json=buttons,
            paused=False,
            created_by=update.effective_user.id,
        )

        slot_times = d.get("daily_slot_times")
        if isinstance(slot_times, list) and len(slot_times) > 0:
            row.daily_slot_times = [str(x).strip() for x in slot_times if x]
        else:
            row.daily_slot_times = None

        pool = d.get("content_pool_json")
        if isinstance(pool, list) and len(pool) > 0:
            row.content_pool_json = pool
        else:
            row.content_pool_json = None

        if d.get("sch_jitter") is not None:
            try:
                row.jitter_seconds = max(0, min(int(d["sch_jitter"]), _MAX_SCHED_JITTER_S))
            except (TypeError, ValueError):
                row.jitter_seconds = None
        else:
            row.jitter_seconds = None

        if sch_kind == ScheduleKind.once.value:
            row.next_run_at = d.get("sch_next_utc")
            row.schedule_summary = "One-time"
        elif sch_kind == ScheduleKind.daily.value:
            if row.daily_slot_times:
                row.time_hhmm = None
                row.next_run_at = d.get("sch_next_utc")
                row.schedule_summary = f"Daily {len(row.daily_slot_times)}× ({tz})"
            else:
                row.time_hhmm = d.get("sch_hhmm")
                row.next_run_at = d.get("sch_next_utc")
                row.schedule_summary = f"Daily {row.time_hhmm} ({tz})"
        elif sch_kind == ScheduleKind.weekly.value:
            row.weekday = int(d.get("sch_weekday"))
            row.time_hhmm = d.get("sch_hhmm")
            row.next_run_at = d.get("sch_next_utc")
            row.schedule_summary = f"Weekly {row.weekday} @ {row.time_hhmm} ({tz})"
        elif sch_kind == ScheduleKind.interval.value:
            row.interval_seconds = int(d.get("sch_interval_s"))
            row.next_run_at = None
            row.schedule_summary = f"Every {row.interval_seconds}s"

        eid = d.get("editing_schedule_id")
        if eid:
            existing = await session.get(Schedule, int(eid))
            if existing:
                pause_saved = existing.paused
                for k in (
                    "title",
                    "kind",
                    "timezone",
                    "content_json",
                    "buttons_json",
                    "next_run_at",
                    "schedule_summary",
                    "time_hhmm",
                    "weekday",
                    "interval_seconds",
                    "daily_slot_times",
                    "content_pool_json",
                    "jitter_seconds",
                ):
                    setattr(existing, k, getattr(row, k))
                existing.paused = pause_saved
                row = existing
        else:
            session.add(row)

        await session.commit()
        await session.refresh(row)

    mgr = BotScheduler.instance()
    if mgr:
        mgr.upsert_job(row)

    reset_fsm(context.user_data)
    await edit_or_send(update, context, text="✅ Schedule saved.", reply_markup=kb_main_menu())


async def _render_schedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Schedule).order_by(Schedule.id.desc()).limit(30))
        rows = list(res.scalars().all())
    if not rows:
        await edit_or_send(
            update,
            context,
            text="<b>📂 Scheduled Posts</b>\n\nNo schedules yet.",
            reply_markup=kb_main_menu(),
        )
        return

    lines = ["<b>📂 Scheduled Posts</b>\n"]
    kb = []
    for i, r in enumerate(rows, start=1):
        status = "⏸️" if r.paused else "▶️"
        lines.append(f"{i}. {status} {esc(r.title)} — <code>{esc(r.schedule_summary or '')}</code>")
        kb.append([InlineKeyboardButton(f"Open #{r.id}", callback_data=f"lst:v:{r.id}")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="m:home")])
    await edit_or_send(update, context, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))


async def _render_schedule_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if not r:
            await edit_or_send(update, context, text="Not found.", reply_markup=kb_main_menu())
            return
        txt = (
            f"<b>Schedule #{r.id}</b>\n"
            f"Title: {esc(r.title)}\n"
            f"Kind: <code>{esc(r.kind)}</code>\n"
            f"Timezone: <code>{esc(r.timezone)}</code>\n"
            f"Paused: <code>{r.paused}</code>\n"
            f"Summary: <code>{esc(r.schedule_summary or '')}</code>\n"
        )
        if r.daily_slot_times:
            txt += f"Daily slots: <code>{esc(str(r.daily_slot_times))}</code>\n"
        if r.content_pool_json:
            txt += f"Content pool entries: <code>{len(r.content_pool_json)}</code> (random each run)\n"
        if r.jitter_seconds:
            txt += f"Jitter (max delay after trigger): <code>{r.jitter_seconds}</code>s\n"
    await edit_or_send(update, context, text=txt, reply_markup=kb_posts_row(sid))


async def _pause_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, paused: bool) -> None:
    factory = get_session_factory()
    row = None
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if r:
            r.paused = paused
            await session.commit()
            row = r
    mgr = BotScheduler.instance()
    if mgr and row:
        mgr.upsert_job(row)
    await _render_schedule_detail(update, context, sid)


async def _delete_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(Schedule).where(Schedule.id == sid))
        await session.commit()
    mgr = BotScheduler.instance()
    if mgr:
        mgr.remove_job(sid)
    await _render_schedule_list(update, context)


async def _begin_schedule_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if not r:
            await edit_or_send(update, context, text="Not found.", reply_markup=kb_main_menu())
            return
        reset_fsm(context.user_data)
        d = get_data(context.user_data)
        d["editing_schedule_id"] = sid
        d["content"] = dict(r.content_json)
        d["buttons"] = r.buttons_json
        d["btn_ctx"] = "sch"
        d["sch_kind"] = r.kind
        d["sch_title"] = r.title
        if r.daily_slot_times:
            d["daily_slot_times"] = list(r.daily_slot_times)
            d["sch_tz_override"] = r.timezone
            d["sch_hhmm"] = None
            if r.jitter_seconds is not None:
                d["sch_jitter"] = int(r.jitter_seconds)
            d["sch_next_utc"] = tzutil.next_daily_multi_slots_at(
                list(r.daily_slot_times), r.timezone, after=datetime.now(tz=timezone.utc)
            )
        if r.content_pool_json:
            d["content_pool_json"] = list(r.content_pool_json)
        if r.daily_slot_times:
            set_state(context.user_data, ST_SCH_PREVIEW)
            from bot.handlers.messages_fsm import _render_sch_preview_panel

            await _render_sch_preview_panel(update, context)
            return

        set_state(context.user_data, ST_SCH_KIND)
        m = await edit_or_send(
            update,
            context,
            text="<b>Edit schedule</b>\n\nPick a new schedule type, then follow the prompts.",
            reply_markup=kb_schedule_kind(),
        )
        _remember_panel_message(m, context.user_data)


async def _render_welcome_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        w = await get_or_create_welcome(session)
        content = effective_welcome_content(w)
        ctype = content.get("type") if content else None
        nrows = len(w.buttons_json or [])
        txt = (
            "<b>👋 Welcome message</b>\n\n"
            f"Enabled: <code>{w.enabled}</code>\n"
            f"Auto-delete: <code>{w.delete_after_seconds or 0}</code>s\n"
            f"Content type: <code>{esc(str(ctype or 'none'))}</code>\n"
            f"Button rows: <code>{nrows}</code>\n"
        )
    await edit_or_send(update, context, text=txt, reply_markup=kb_welcome_menu())


async def _render_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        s = await get_or_create_settings(session)
        txt = (
            "<b>⚙️ Settings</b>\n\n"
            f"Target channel id: <code>{s.target_channel_id}</code>\n"
            f"Discussion group id: <code>{s.discussion_group_id}</code>\n"
            f"Timezone: <code>{esc(s.timezone)}</code>\n"
            f"Logs: <code>{s.logs_enabled}</code>\n"
        )
    await edit_or_send(update, context, text=txt, reply_markup=kb_settings_menu())


async def _render_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started = context.bot_data.get("started_at") or datetime.now(tz=timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        snap = await stats_snapshot(session, started_at=started)
    txt = (
        "<b>📊 Statistics</b>\n\n"
        "<b>Channel subscribers</b>\n"
        f"Active (still in channel): <code>{snap['active_subscribers']}</code>\n"
        f"Welcome pending (no successful welcome DM yet): <code>{snap['pending_welcome']}</code>\n"
        "<i>Subscribers are recorded on channel join; DMs require users to /start the bot.</i>\n\n"
        "<b>Users</b>\n"
        f"Total who used /start: <code>{snap['total_bot_users']}</code>\n"
        f"Active (last 7 days): <code>{snap['active_users_7d']}</code>\n"
        f"Active (last 30 days): <code>{snap['active_users_30d']}</code>\n\n"
        "<b>Channel posts (via bot, logged)</b>\n"
        f"Total delivered: <code>{snap['channel_posts_logged']}</code>\n"
        "<i>Counts broadcasts, scheduler runs, welcome test-to-channel, and subscriber DMs.</i>\n\n"
        "<b>Schedules</b>\n"
        f"Total schedule rows: <code>{snap['total_schedules']}</code>\n"
        f"Active (not paused): <code>{snap['active_schedules']}</code>\n\n"
        "<b>Broadcasts and health</b>\n"
        f"Broadcast log rows: <code>{snap['total_broadcasts']}</code>\n"
        f"Failed deliveries: <code>{snap['failed_deliveries']}</code>\n"
        f"Uptime (s): <code>{snap['uptime_seconds']}</code>\n"
    )
    await edit_or_send(update, context, text=txt, reply_markup=kb_stats_refresh())
