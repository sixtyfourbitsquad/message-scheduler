"""Telegram UI for prediction engine (sets, media capture, schedule controls, stats)."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm.attributes import flag_modified
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.database.session import get_session_factory
from bot.handlers.helpers import edit_or_send, esc
from bot.keyboards.prediction_admin_kb import (
    pred_hub_kb,
    pred_schedule_engine_kb,
    pred_schedule_opts_kb,
    pred_set_delete_confirm_kb,
    pred_set_detail_kb,
    pred_sets_list_kb,
    pred_schedules_kb,
    pred_stats_kb,
)
from bot.models.prediction_engine_state import PredictionEngineState
from bot.models.prediction_run_log import PredictionRunLog
from bot.models.prediction_set import PredictionSet
from bot.models.schedule import Schedule
from bot.scheduler.manager import BotScheduler
from bot.services.content_poster import send_content_to_chat
from bot.services.prediction_engine_service import run_prediction_cycle
from bot.services.settings_service import get_or_create_settings
from bot.utils.fsm import get_data, get_state, reset_fsm, set_state
from bot.utils.message_serialize import message_to_content_dict

log = logging.getLogger(__name__)

ST_PRED_TEXT = "pred_text"
ST_PRED_MEDIA = "pred_media"
ST_PRED_STICK = "pred_stick"


def _remember_panel(update: Update, user_data: dict) -> None:
    q = update.callback_query
    if q and q.message:
        user_data["panel_chat_id"] = q.message.chat_id
        user_data["panel_message_id"] = q.message.message_id


def _empty_payload() -> dict[str, Any]:
    return {
        "templates": [],
        "win_stickers": [],
        "loss_stickers": [],
        "result_images": [],
        "captions": [],
        "registers": [],
        "warnings": [],
    }


def _payload_deep(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Deep copy for safe JSONB mutations (SQLAlchemy detects reassignment)."""
    return deepcopy(_norm_payload(raw))


def _norm_payload(raw: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(raw or {})
    for k, default in _empty_payload().items():
        p.setdefault(k, list(default) if isinstance(default, list) else default)
    if not isinstance(p["templates"], list):
        p["templates"] = []
    if not isinstance(p["win_stickers"], list):
        p["win_stickers"] = []
    if not isinstance(p["loss_stickers"], list):
        p["loss_stickers"] = []
    if not isinstance(p["result_images"], list):
        p["result_images"] = []
    if not isinstance(p["captions"], list):
        p["captions"] = []
    if not isinstance(p["registers"], list):
        p["registers"] = []
    if not isinstance(p["warnings"], list):
        p["warnings"] = []
    return p


def _compose_set_detail_view(r: PredictionSet) -> tuple[str, InlineKeyboardMarkup]:
    sid = int(r.id)
    p = _norm_payload(r.payload)
    name, active, premium, weight = r.name, r.active, r.is_premium, r.weight
    extra: list[list[InlineKeyboardButton]] = []
    for cat, label, nkey, mx in (
        ("win", "WIN", "win_stickers", 4),
        ("los", "LOSS", "loss_stickers", 4),
        ("tpl", "Tpl", "templates", 3),
        ("img", "Res", "result_images", 3),
        ("cap", "Cap", "captions", 4),
        ("reg", "Reg", "registers", 3),
        ("war", "War", "warnings", 3),
    ):
        arr = p.get(nkey) or []
        for i, _it in enumerate(arr[:mx]):
            extra.append(
                [
                    InlineKeyboardButton(
                        f"🗑️ {label} {i}",
                        callback_data=f"pred:rm:{sid}:{cat}:{i}",
                    )
                ]
            )

    txt = (
        f"<b>Set #{sid}</b> — {esc(name)}\n"
        f"Weight: <code>{weight}</code> · Premium: <code>{premium}</code> · Active: <code>{active}</code>\n\n"
        f"Templates: <code>{len(p['templates'])}</code>\n"
        f"WIN stickers: <code>{len(p['win_stickers'])}</code> · LOSS: <code>{len(p['loss_stickers'])}</code>\n"
        f"Result media: <code>{len(p['result_images'])}</code>\n"
        f"Captions: <code>{len(p['captions'])}</code> · Register lines: <code>{len(p['registers'])}</code> · Warnings: <code>{len(p['warnings'])}</code>"
    )
    markup = pred_set_detail_kb(sid, active, premium)
    base = list(markup.inline_keyboard)
    rows = base[:-2] + extra + base[-2:]
    return txt, InlineKeyboardMarkup(rows)


async def _refresh_set_detail_panel(context: ContextTypes.DEFAULT_TYPE, user_data: dict, sid: int) -> None:
    """Re-edit the dashboard panel message so counts stay in sync after uploads."""
    chat_id = user_data.get("panel_chat_id")
    mid = user_data.get("panel_message_id")
    if not chat_id or not mid:
        return
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if not r:
            return
        txt, kb = _compose_set_detail_view(r)
    try:
        await context.bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(mid),
            text=txt,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        log.info("prediction set panel refresh skipped: %s", e)


async def render_pred_hub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reset_fsm(context.user_data)
    factory = get_session_factory()
    async with factory() as session:
        n_tot = (await session.execute(select(func.count()).select_from(PredictionSet))).scalar_one()
        n_act = (
            await session.execute(select(func.count()).select_from(PredictionSet).where(PredictionSet.active.is_(True)))
        ).scalar_one()
    txt = (
        "<b>🎲 Prediction engine</b>\n\n"
        "Manage sets, uploads, schedule bindings, and tests — no SQL required.\n\n"
        f"Sets: <code>{n_tot}</code> total · <code>{n_act}</code> active\n"
        "Use <b>Sets</b> to add WIN/LOSS stickers, templates, result media, captions, register &amp; warning lines.\n"
        "Use <b>Schedules</b> to enable the engine per schedule, tune delays, and run a test post to the channel."
    )
    m = await edit_or_send(update, context, text=txt, reply_markup=pred_hub_kb())
    _remember_panel(update, context.user_data)


async def dispatch_pred_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != "pred":
        return
    op = parts[1]

    if op in ("hub", "info"):
        await render_pred_hub(update, context)
        return

    if op == "sets":
        await _render_sets_list(update, context)
        return
    if op == "new":
        d = get_data(context.user_data)
        d.clear()
        d["pred_expect"] = "new_set_name"
        set_state(context.user_data, ST_PRED_TEXT)
        await edit_or_send(
            update,
            context,
            text="<b>New prediction set</b>\n\nSend a short <b>name</b> for this set (plain text).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="pred:hub")]]),
        )
        _remember_panel(update, context.user_data)
        return

    if op == "stats":
        await _render_stats(update, context)
        return

    if op == "sch":
        await _render_schedules_pred(update, context)
        return

    if op in ("ps", "rs") and len(parts) >= 3 and parts[2] == "all":
        await _pause_resume_all_engine(update, context, pause=(op == "ps"))
        return

    if op == "set" and len(parts) >= 3 and parts[2].isdigit():
        await _render_set_detail(update, context, int(parts[2]))
        return

    if op == "pv" and len(parts) >= 3 and parts[2].isdigit():
        await _preview_set(update, context, int(parts[2]))
        return

    if op == "at" and len(parts) >= 3 and parts[2].isdigit():
        await _toggle_set_active(update, context, int(parts[2]))
        return
    if op == "pm" and len(parts) >= 3 and parts[2].isdigit():
        await _toggle_set_premium(update, context, int(parts[2]))
        return

    if op == "ne" and len(parts) >= 3 and parts[2].isdigit():
        sid = int(parts[2])
        d = get_data(context.user_data)
        d.clear()
        d["pred_set_id"] = sid
        d["pred_expect"] = "rename_set"
        set_state(context.user_data, ST_PRED_TEXT)
        await edit_or_send(
            update,
            context,
            text="<b>Rename set</b>\n\nSend the new name (plain text).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"pred:set:{sid}")]]),
        )
        _remember_panel(update, context.user_data)
        return

    if op == "nw" and len(parts) >= 3 and parts[2].isdigit():
        sid = int(parts[2])
        d = get_data(context.user_data)
        d.clear()
        d["pred_set_id"] = sid
        d["pred_expect"] = "set_weight"
        set_state(context.user_data, ST_PRED_TEXT)
        await edit_or_send(
            update,
            context,
            text="<b>Set weight</b>\n\nSend a positive number (e.g. <code>1.0</code>). Higher = picked more often.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"pred:set:{sid}")]]),
        )
        _remember_panel(update, context.user_data)
        return

    if op in ("wt", "lt", "tm", "ri", "ca", "rg", "wr") and len(parts) >= 3 and parts[2].isdigit():
        sid = int(parts[2])
        d = get_data(context.user_data)
        d.clear()
        d["pred_set_id"] = sid
        if op == "wt":
            d["pred_expect"] = "win_sticker"
            set_state(context.user_data, ST_PRED_STICK)
            hint = "Send a <b>sticker</b> (static or animated)."
        elif op == "lt":
            d["pred_expect"] = "loss_sticker"
            set_state(context.user_data, ST_PRED_STICK)
            hint = "Send a <b>sticker</b> (static or animated)."
        elif op == "tm":
            d["pred_expect"] = "template"
            set_state(context.user_data, ST_PRED_MEDIA)
            hint = "Send a <b>prediction message</b> (text, photo, video, GIF, etc.)."
        elif op == "ri":
            d["pred_expect"] = "result_image"
            set_state(context.user_data, ST_PRED_MEDIA)
            hint = "Send a <b>result image/video/GIF</b> (same formats as scheduled posts)."
        elif op == "ca":
            d["pred_expect"] = "caption"
            set_state(context.user_data, ST_PRED_TEXT)
            hint = "Send a <b>caption line</b> (plain text) for result images."
        elif op == "rg":
            d["pred_expect"] = "register"
            set_state(context.user_data, ST_PRED_TEXT)
            hint = "Send a <b>register line</b> (plain text), shown sometimes before the signal."
        else:
            d["pred_expect"] = "warning"
            set_state(context.user_data, ST_PRED_TEXT)
            hint = "Send a <b>warning line</b> (plain text), shown sometimes after the signal."
        await edit_or_send(
            update,
            context,
            text=f"<b>Add to set #{sid}</b>\n\n{hint}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"pred:set:{sid}")]]),
        )
        _remember_panel(update, context.user_data)
        return

    if op == "dl" and len(parts) >= 3 and parts[2].isdigit():
        sid = int(parts[2])
        await edit_or_send(
            update,
            context,
            text=f"<b>Delete set #{sid}?</b>\n\nThis cannot be undone.",
            reply_markup=pred_set_delete_confirm_kb(sid),
        )
        return

    if op == "dy" and len(parts) >= 3 and parts[2].isdigit():
        await _delete_set_confirmed(update, context, int(parts[2]))
        return

    if op == "rm" and len(parts) >= 5 and parts[2].isdigit() and parts[4].isdigit():
        await _remove_pool_item(update, context, int(parts[2]), parts[3], int(parts[4]))
        return

    if op == "sg" and len(parts) >= 3 and parts[2].isdigit():
        await _render_schedule_pred_panel(update, context, int(parts[2]))
        return

    if op == "eg" and len(parts) >= 3 and parts[2].isdigit():
        await _toggle_schedule_engine(update, context, int(parts[2]))
        return

    if op == "try" and len(parts) >= 3 and parts[2].isdigit():
        await _manual_test_run(update, context, int(parts[2]))
        return

    if op == "op" and len(parts) >= 3 and parts[2].isdigit():
        sid = int(parts[2])
        await edit_or_send(
            update,
            context,
            text=f"<b>Engine options — schedule #{sid}</b>\n\nPick a field to edit (send value in chat).",
            reply_markup=pred_schedule_opts_kb(sid),
        )
        return

    if op in ("dm", "dv", "rp", "wp") and len(parts) >= 3 and parts[2].isdigit():
        sch_id = int(parts[2])
        d = get_data(context.user_data)
        d.clear()
        d["pred_sched_id"] = sch_id
        if op == "dm":
            d["pred_expect"] = "delay_min"
            msg = "Send <b>min delay</b> seconds between signal and result (e.g. <code>0.8</code>)."
        elif op == "dv":
            d["pred_expect"] = "delay_max"
            msg = "Send <b>max delay</b> seconds (e.g. <code>5</code>)."
        elif op == "rp":
            d["pred_expect"] = "reg_prob"
            msg = "Send <b>register line probability</b> between 0 and 1 (e.g. <code>0.2</code>)."
        else:
            d["pred_expect"] = "war_prob"
            msg = "Send <b>warning line probability</b> between 0 and 1 (e.g. <code>0.25</code>)."
        set_state(context.user_data, ST_PRED_TEXT)
        await edit_or_send(
            update,
            context,
            text=f"<b>Schedule #{sch_id}</b>\n\n{msg}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"pred:op:{sch_id}")]]),
        )
        _remember_panel(update, context.user_data)
        return

    if op == "ty0" and len(parts) >= 3 and parts[2].isdigit():
        await _set_typing(update, context, int(parts[2]), False)
        return
    if op == "ty1" and len(parts) >= 3 and parts[2].isdigit():
        await _set_typing(update, context, int(parts[2]), True)
        return

    if op == "zp" and len(parts) >= 3 and parts[2].isdigit():
        await _set_schedule_paused(update, context, int(parts[2]), True)
        return
    if op == "zr" and len(parts) >= 3 and parts[2].isdigit():
        await _set_schedule_paused(update, context, int(parts[2]), False)
        return


async def handle_prediction_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if this message was consumed by prediction-admin FSM."""
    ud = context.user_data
    st = get_state(ud)
    if st not in (ST_PRED_TEXT, ST_PRED_MEDIA, ST_PRED_STICK):
        return False
    msg = update.message
    if not msg:
        return False

    d = get_data(ud)
    expect = d.get("pred_expect")
    if not expect:
        set_state(ud, None)
        return False

    factory = get_session_factory()

    if st == ST_PRED_TEXT and isinstance(expect, str):
        text = (msg.text or "").strip()
        if expect == "new_set_name":
            if not text:
                await msg.reply_text("Send a non-empty name.")
                return True
            async with factory() as session:
                row = PredictionSet(name=text[:128], weight=1.0, is_premium=False, active=True, payload=_empty_payload())
                session.add(row)
                await session.commit()
                await session.refresh(row)
            set_state(ud, None)
            await msg.reply_text(f"✅ Created set #{row.id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open set", callback_data=f"pred:set:{row.id}")]]))
            return True

        if expect == "rename_set":
            sid = int(d.get("pred_set_id") or 0)
            async with factory() as session:
                r = await session.get(PredictionSet, sid)
                if r:
                    r.name = text[:128]
                    await session.commit()
            set_state(ud, None)
            await msg.reply_text("✅ Name updated.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to set", callback_data=f"pred:set:{sid}")]]))
            return True

        if expect == "set_weight":
            sid = int(d.get("pred_set_id") or 0)
            try:
                w = float(text.replace(",", "."))
                if w <= 0:
                    raise ValueError
            except Exception:
                await msg.reply_text("Send a positive number.")
                return True
            async with factory() as session:
                r = await session.get(PredictionSet, sid)
                if r:
                    r.weight = w
                    await session.commit()
            set_state(ud, None)
            await msg.reply_text("✅ Weight updated.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"pred:set:{sid}")]]))
            return True

        if expect in ("caption", "register", "warning"):
            sid = int(d.get("pred_set_id") or 0)
            if not text:
                await msg.reply_text("Send non-empty text.")
                return True
            key = {"caption": "captions", "register": "registers", "warning": "warnings"}[expect]
            async with factory() as session:
                r = await session.get(PredictionSet, sid)
                if r:
                    p = _payload_deep(r.payload)
                    p[key].append(text)
                    r.payload = p
                    flag_modified(r, "payload")
                    await session.commit()
            set_state(ud, None)
            await _refresh_set_detail_panel(context, ud, sid)
            await msg.reply_text("✅ Added — panel counts updated.")
            return True

        if expect in ("delay_min", "delay_max", "reg_prob", "war_prob"):
            sch_id = int(d.get("pred_sched_id") or 0)
            try:
                val = float(text.replace(",", "."))
            except Exception:
                await msg.reply_text("Send a number.")
                return True
            opt_key = {
                "delay_min": "inter_message_delay_min",
                "delay_max": "inter_message_delay_max",
                "reg_prob": "register_probability",
                "war_prob": "warning_probability",
            }[expect]
            if expect in ("reg_prob", "war_prob"):
                val = max(0.0, min(1.0, val))
            elif expect == "delay_min" and val < 0.1:
                await msg.reply_text("Min delay should be ≥ 0.1")
                return True
            async with factory() as session:
                sch = await session.get(Schedule, sch_id)
                if sch:
                    opts = dict(sch.prediction_options or {})
                    opts[opt_key] = val
                    if expect == "delay_min" and float(opts.get("inter_message_delay_max", 4.5)) < val:
                        opts["inter_message_delay_max"] = val + 0.5
                    if expect == "delay_max" and float(opts.get("inter_message_delay_min", 0.65)) > val:
                        opts["inter_message_delay_min"] = max(0.2, val - 0.5)
                    sch.prediction_options = opts
                    await session.commit()
            set_state(ud, None)
            await msg.reply_text("✅ Saved.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Options", callback_data=f"pred:op:{sch_id}")]]))
            return True

    if st == ST_PRED_STICK and expect in ("win_sticker", "loss_sticker"):
        sid = int(d.get("pred_set_id") or 0)
        sti = msg.sticker
        if not sti:
            await msg.reply_text(
                "Send an actual <b>sticker</b> (tap the sticker tray — emoji typed as text is not stored).\n"
                "Animated / video stickers work.",
                parse_mode=ParseMode.HTML,
            )
            return True
        fid = sti.file_id
        key = "win_stickers" if expect == "win_sticker" else "loss_stickers"
        async with factory() as session:
            r = await session.get(PredictionSet, sid)
            if r:
                p = _payload_deep(r.payload)
                p[key].append(fid)
                r.payload = p
                flag_modified(r, "payload")
                await session.commit()
        set_state(ud, None)
        await _refresh_set_detail_panel(context, ud, sid)
        await msg.reply_text("✅ Sticker saved — check updated counts on the panel above.")
        return True

    if st == ST_PRED_MEDIA and expect in ("template", "result_image"):
        sid = int(d.get("pred_set_id") or 0)
        payload = message_to_content_dict(msg)
        if payload.get("type") == "unsupported":
            await msg.reply_text(payload.get("hint", "Unsupported."))
            return True
        async with factory() as session:
            r = await session.get(PredictionSet, sid)
            if r:
                p = _payload_deep(r.payload)
                if expect == "template":
                    p["templates"].append(payload)
                else:
                    p["result_images"].append(payload)
                r.payload = p
                flag_modified(r, "payload")
                await session.commit()
        set_state(ud, None)
        await _refresh_set_detail_panel(context, ud, sid)
        await msg.reply_text("✅ Saved — panel counts updated.")
        return True

    return False


async def _preview_set(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    """Send sample messages to the admin's private chat (does not post to channel)."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return

    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if not r:
            await edit_or_send(update, context, text="Set not found.", reply_markup=pred_hub_kb())
            return
        p = _norm_payload(r.payload)

    templates = [
        t for t in (p.get("templates") or []) if isinstance(t, dict) and t.get("type") not in (None, "unsupported")
    ]
    if not templates:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"<b>Preview — set #{sid}</b>\n\n"
                "Add at least one <b>Template</b> first, then preview again.\n"
                "Stickers alone are not shown until there is a template (channel runs need it)."
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"<b>Preview — set #{sid}</b>\n<i>Only you receive these messages.</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(0.2)

    await send_content_to_chat(context.bot, chat_id=chat_id, content=dict(templates[0]), buttons_json=None)
    await asyncio.sleep(0.25)

    wins = [x for x in (p.get("win_stickers") or []) if isinstance(x, str) and len(x) > 3]
    losses = [x for x in (p.get("loss_stickers") or []) if isinstance(x, str) and len(x) > 3]
    if wins:
        await context.bot.send_message(chat_id=chat_id, text="WIN sticker (sample):", parse_mode=ParseMode.HTML)
        await context.bot.send_sticker(chat_id=chat_id, sticker=wins[0])
        await asyncio.sleep(0.2)
    if losses:
        await context.bot.send_message(chat_id=chat_id, text="LOSS sticker (sample):", parse_mode=ParseMode.HTML)
        await context.bot.send_sticker(chat_id=chat_id, sticker=losses[0])
        await asyncio.sleep(0.2)

    imgs = [x for x in (p.get("result_images") or []) if isinstance(x, dict) and x.get("type") and x.get("file_id")]
    if imgs:
        await context.bot.send_message(chat_id=chat_id, text="Result media (sample):", parse_mode=ParseMode.HTML)
        await send_content_to_chat(context.bot, chat_id=chat_id, content=dict(imgs[0]), buttons_json=None)

    regs = [x for x in (p.get("registers") or []) if isinstance(x, str) and x.strip()]
    warns = [x for x in (p.get("warnings") or []) if isinstance(x, str) and x.strip()]
    if regs:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>Register line</b> (may appear before signal):\n{esc(regs[0])}",
            parse_mode=ParseMode.HTML,
        )
    if warns:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>Warning line</b> (may appear after signal):\n{esc(warns[0])}",
            parse_mode=ParseMode.HTML,
        )


# --- panels ---


async def _render_sets_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(PredictionSet).order_by(PredictionSet.id.desc()).limit(40))
        rows_db = list(res.scalars().all())
    if not rows_db:
        await edit_or_send(
            update,
            context,
            text="<b>Prediction sets</b>\n\nNo sets yet. Tap <b>New set</b>.",
            reply_markup=pred_sets_list_kb([]),
        )
        return
    lines = ["<b>Prediction sets</b>\n"]
    kb_rows: list[list[InlineKeyboardButton]] = []
    for r in rows_db:
        flag = "✅" if r.active else "⏸️"
        pr = "⭐" if r.is_premium else ""
        lines.append(f"{flag}{pr} <code>{r.id}</code> — {esc(r.name)} (w={r.weight})")
        kb_rows.append([InlineKeyboardButton(f"#{r.id} {r.name[:20]}", callback_data=f"pred:set:{r.id}")])
    await edit_or_send(update, context, text="\n".join(lines), reply_markup=pred_sets_list_kb(kb_rows))


async def _render_set_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if not r:
            await edit_or_send(update, context, text="Set not found.", reply_markup=pred_hub_kb())
            return
        txt, kb = _compose_set_detail_view(r)
    m = await edit_or_send(update, context, text=txt, reply_markup=kb)
    context.user_data["panel_chat_id"] = m.chat_id
    context.user_data["panel_message_id"] = m.message_id


async def _toggle_set_active(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if r:
            r.active = not bool(r.active)
            await session.commit()
    await _render_set_detail(update, context, sid)


async def _toggle_set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if r:
            r.is_premium = not bool(r.is_premium)
            await session.commit()
    await _render_set_detail(update, context, sid)


async def _delete_set_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(PredictionSet).where(PredictionSet.id == sid))
        await session.commit()
    await _render_sets_list(update, context)


async def _remove_pool_item(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, cat: str, idx: int) -> None:
    key_map = {
        "win": "win_stickers",
        "los": "loss_stickers",
        "tpl": "templates",
        "img": "result_images",
        "cap": "captions",
        "reg": "registers",
        "war": "warnings",
    }
    key = key_map.get(cat)
    if not key:
        await _render_set_detail(update, context, sid)
        return
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(PredictionSet, sid)
        if not r:
            await render_pred_hub(update, context)
            return
        p = _payload_deep(r.payload)
        arr = list(p.get(key) or [])
        if 0 <= idx < len(arr):
            arr.pop(idx)
            p[key] = arr
            r.payload = p
            flag_modified(r, "payload")
            await session.commit()
    await _render_set_detail(update, context, sid)


async def _render_schedules_pred(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Schedule).order_by(Schedule.id.desc()).limit(35))
        rows = list(res.scalars().all())
    if not rows:
        await edit_or_send(update, context, text="<b>Schedules</b>\n\nNo schedules.", reply_markup=pred_hub_kb())
        return
    lines = ["<b>Schedules</b>\n\nTap one to configure prediction engine binding.\n"]
    kb: list[list[InlineKeyboardButton]] = []
    for r in rows:
        eng = "🎲" if r.use_prediction_engine else "📄"
        ps = "⏸️" if r.paused else "▶️"
        lines.append(f"{eng}{ps} <code>{r.id}</code> {esc(r.title[:40])}")
        kb.append([InlineKeyboardButton(f"#{r.id}", callback_data=f"pred:sg:{r.id}")])
    await edit_or_send(update, context, text="\n".join(lines), reply_markup=pred_schedules_kb(kb))


async def _render_schedule_pred_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if not r:
            await edit_or_send(update, context, text="Not found.", reply_markup=pred_hub_kb())
            return
        opts = r.prediction_options or {}
        stt = await session.get(PredictionEngineState, sid)
        last = (stt.state_json or {}).get("last_set_id") if stt else None
        wt = (stt.state_json or {}).get("win_total") if stt else None
        lt = (stt.state_json or {}).get("loss_total") if stt else None
    txt = (
        f"<b>Schedule #{sid}</b> — {esc(r.title)}\n"
        f"Prediction engine: <code>{r.use_prediction_engine}</code>\n"
        f"Paused: <code>{r.paused}</code>\n"
        f"Options: <code>{esc(str(opts))}</code>\n"
        f"State — last set: <code>{last}</code> · wins: <code>{wt}</code> · losses: <code>{lt}</code>"
    )
    await edit_or_send(update, context, text=txt, reply_markup=pred_schedule_engine_kb(sid, r.use_prediction_engine))


async def _toggle_schedule_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    row = None
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if r:
            r.use_prediction_engine = not bool(r.use_prediction_engine)
            if r.use_prediction_engine and not r.prediction_options:
                r.prediction_options = {
                    "typing": True,
                    "typing_before_media": True,
                    "inter_message_delay_min": 0.65,
                    "inter_message_delay_max": 4.5,
                    "register_probability": 0.18,
                    "warning_probability": 0.26,
                }
            await session.commit()
            row = r
    mgr = BotScheduler.instance()
    if mgr and row:
        mgr.upsert_job(row)
    await _render_schedule_pred_panel(update, context, sid)


async def _set_schedule_paused(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, paused: bool) -> None:
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
    await _render_schedule_pred_panel(update, context, sid)


async def _set_typing(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, on: bool) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.get(Schedule, sid)
        if r:
            opts = dict(r.prediction_options or {})
            opts["typing"] = on
            opts["typing_before_media"] = on
            r.prediction_options = opts
            await session.commit()
    await edit_or_send(
        update,
        context,
        text=f"✅ Typing simulation set to <code>{on}</code> for schedule #{sid}.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Options", callback_data=f"pred:op:{sid}")]]),
    )


async def _pause_resume_all_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, *, pause: bool) -> None:
    factory = get_session_factory()
    async with factory() as session:
        res = await session.execute(select(Schedule).where(Schedule.use_prediction_engine.is_(True)))
        n = 0
        for r in res.scalars():
            r.paused = pause
            n += 1
        await session.commit()
    mgr = BotScheduler.instance()
    if mgr:
        await mgr.reload_from_db()
    verb = "Paused" if pause else "Resumed"
    await edit_or_send(
        update,
        context,
        text=f"<b>{verb}</b> <code>{n}</code> schedule(s) with prediction engine enabled.",
        reply_markup=pred_hub_kb(),
    )


async def _manual_test_run(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        sch = await session.get(Schedule, sid)
        cfg = await get_or_create_settings(session)
        ch = cfg.target_channel_id
        if not sch or not ch:
            await edit_or_send(update, context, text="Missing schedule or target channel in Settings.", reply_markup=pred_hub_kb())
            return
        ok = await run_prediction_cycle(
            context.bot,
            session,
            schedule=sch,
            channel_id=int(ch),
            buttons_json=sch.buttons_json,
            manual_test=True,
        )
        await session.commit()
    txt = "✅ Test cycle completed (check the channel)." if ok else "❌ Test failed — add active sets with templates, or check logs."
    await edit_or_send(
        update,
        context,
        text=txt,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Schedule", callback_data=f"pred:sg:{sid}")]]),
    )


async def _render_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = get_session_factory()
    async with factory() as session:
        n_tot = (await session.execute(select(func.count()).select_from(PredictionSet))).scalar_one()
        n_act = (
            await session.execute(select(func.count()).select_from(PredictionSet).where(PredictionSet.active.is_(True)))
        ).scalar_one()
        n_logs = (await session.execute(select(func.count()).select_from(PredictionRunLog))).scalar_one()
        res = await session.execute(select(PredictionRunLog).order_by(PredictionRunLog.id.desc()).limit(12))
        recent = list(res.scalars().all())
        wn = (
            await session.execute(
                select(func.count())
                .select_from(PredictionRunLog)
                .where(and_(PredictionRunLog.outcome == "W", PredictionRunLog.ok.is_(True)))
            )
        ).scalar_one()
        ls = (
            await session.execute(
                select(func.count())
                .select_from(PredictionRunLog)
                .where(and_(PredictionRunLog.outcome == "L", PredictionRunLog.ok.is_(True)))
            )
        ).scalar_one()
    lines = [
        "<b>Prediction stats</b>\n",
        f"Sets total: <code>{n_tot}</code> · active: <code>{n_act}</code>",
        f"Logged runs: <code>{n_logs}</code> · wins: <code>{wn}</code> · losses: <code>{ls}</code>\n",
        "<b>Recent runs</b>",
    ]
    for lg in recent:
        mt = " (test)" if lg.manual_test else ""
        lines.append(
            f"<code>{esc(str(lg.created_at))}</code> sch={lg.schedule_id} set={lg.set_id} {lg.outcome or '-'} ok={lg.ok}{mt}"
        )
    await edit_or_send(update, context, text="\n".join(lines), reply_markup=pred_stats_kb())
