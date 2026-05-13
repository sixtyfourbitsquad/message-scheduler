"""
Dynamic prediction cycles: weighted sets, anti-repeat memory, typing simulation.

Telegram only accepts uploaded `file_id` values in production — use `payload` JSON in
`prediction_sets` (populate via SQL or tooling). Optional local folders under `assets/`
are for your own organization before you copy file_ids into the DB.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.constants import ChatAction

from bot.models.prediction_engine_state import PredictionEngineState
from bot.models.prediction_set import PredictionSet
from bot.models.schedule import Schedule
from bot.services.content_poster import send_content_to_chat

log = logging.getLogger(__name__)

_SET_RING = 6
_STICKER_RING = 5
_CAPTION_RING = 4
_SEQ_RING = 10


def _eff_weight(s: PredictionSet) -> float:
    w = float(s.weight or 1.0)
    if s.is_premium:
        w *= 0.22
    return max(0.05, w)


def _ring_push_str(ring: list[str], val: str, maxlen: int) -> list[str]:
    ring = [x for x in ring if x != val]
    ring.append(val)
    return ring[-maxlen:]


def _ring_push_int(ring: list[int], val: int, maxlen: int) -> list[int]:
    ring = [x for x in ring if x != val]
    ring.append(val)
    return ring[-maxlen:]


def _pick_from_pool_str(pool: list[str], recent: list[str], avoid_last: int) -> str:
    tail = set(recent[-avoid_last:])
    alt = [x for x in pool if x not in tail] or pool
    return random.choice(alt)


def _pick_outcome(state: dict[str, Any]) -> str:
    out = state.get("recent_outcomes") or []
    tail = "".join(str(x) for x in out[-2:])
    r = random.random()
    if tail == "WW" and r < 0.52:
        return "L"
    if tail == "LL" and r < 0.58:
        return "W"
    if tail == "WL" and r < 0.38:
        return "L"
    if r < 0.57:
        return "W"
    return "L"


async def _chat_action(bot: Bot, chat_id: int, *, typing: bool, media: bool) -> None:
    if not typing:
        return
    try:
        await bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.UPLOAD_PHOTO if media else ChatAction.TYPING,
        )
    except Exception:
        pass
    await asyncio.sleep(random.uniform(0.35, 1.65))


async def run_prediction_cycle(
    bot: Bot,
    session: AsyncSession,
    *,
    schedule: Schedule,
    channel_id: int,
    buttons_json: list[list[dict[str, str]]] | None,
) -> bool:
    """
    Send a short organic-looking sequence: prediction text → pause → result (sticker or media).

    Updates `prediction_engine_states` for `schedule.id` (anti-repeat + outcome streaks).
    """
    res = await session.execute(
        select(PredictionSet).where(PredictionSet.active.is_(True)).order_by(PredictionSet.id)
    )
    sets = list(res.scalars().all())
    if not sets:
        log.warning("use_prediction_engine on schedule %s but no active prediction_sets", schedule.id)
        return False

    st = await session.get(PredictionEngineState, int(schedule.id))
    if st is None:
        st = PredictionEngineState(
            schedule_id=int(schedule.id),
            channel_id=int(channel_id),
            state_json={},
        )
        session.add(st)
        await session.flush()
    state: dict[str, Any] = dict(st.state_json or {})

    opts = schedule.prediction_options or {}
    typing_sim = bool(opts.get("typing", True))
    typing_media = bool(opts.get("typing_before_media", True))
    inter_max = max(1.0, float(opts.get("inter_message_delay_max", 4.5) or 4.5))
    inter_min = float(opts.get("inter_message_delay_min", 0.65) or 0.65)
    inter_min = max(0.2, min(inter_min, inter_max))

    raw_ids = state.get("recent_set_ids") or []
    recent_set_ids: list[int] = []
    for x in raw_ids:
        try:
            recent_set_ids.append(int(x))
        except (TypeError, ValueError):
            continue
    weights: list[float] = []
    for s in sets:
        w = _eff_weight(s)
        if s.id in recent_set_ids[-2:]:
            w *= 0.15
        weights.append(w)
    chosen: PredictionSet = random.choices(sets, weights=weights, k=1)[0]
    payload = chosen.payload or {}

    templates = [
        t for t in (payload.get("templates") or []) if isinstance(t, dict) and t.get("type") not in (None, "unsupported")
    ]
    if not templates:
        log.warning("prediction set %s has no valid templates", chosen.id)
        return False

    tmpl_keys: list[str] = []
    tmpl_by_key: dict[str, dict[str, Any]] = {}
    for i, t in enumerate(templates):
        h = hashlib.sha1(json.dumps(t, sort_keys=True).encode()).hexdigest()[:10]
        key = f"{chosen.id}:{i}:{h}"
        tmpl_keys.append(key)
        tmpl_by_key[key] = t

    recent_tmpl = list(state.get("recent_template_keys") or [])
    tmpl_pool = [k for k in tmpl_keys if k not in recent_tmpl[-3:]] or tmpl_keys

    outcome = _pick_outcome(state)
    seq_prev = list(state.get("recent_sequences") or [])
    tail_sigs = set(seq_prev[-8:])
    alt_keys = [k for k in tmpl_pool if f"{chosen.id}|{outcome}|{k}" not in tail_sigs]
    pool_for_tmpl = alt_keys or tmpl_pool
    tkey = random.choice(pool_for_tmpl)
    tmpl = tmpl_by_key[tkey]
    sig_try = f"{chosen.id}|{outcome}|{tkey}"
    if sig_try in tail_sigs and len(tmpl_pool) > 1:
        flipped = "L" if outcome == "W" else "W"
        alt2 = [k for k in tmpl_pool if f"{chosen.id}|{flipped}|{k}" not in tail_sigs]
        if alt2:
            outcome = flipped
            tkey = random.choice(alt2)
            tmpl = tmpl_by_key[tkey]

    win_stickers = [x for x in (payload.get("win_stickers") or []) if isinstance(x, str) and len(x) > 3]
    loss_stickers = [x for x in (payload.get("loss_stickers") or []) if isinstance(x, str) and len(x) > 3]
    result_images = [
        x for x in (payload.get("result_images") or []) if isinstance(x, dict) and x.get("type") and x.get("file_id")
    ]
    captions = [x for x in (payload.get("captions") or []) if isinstance(x, str) and x.strip()]

    await _chat_action(bot, channel_id, typing=typing_sim, media=False)
    mid = await send_content_to_chat(bot, chat_id=channel_id, content=tmpl, buttons_json=buttons_json)
    if not mid:
        return False

    await asyncio.sleep(random.uniform(inter_min, inter_max))

    recent_stickers = list(state.get("recent_sticker_ids") or [])
    recent_caps = list(state.get("recent_caption_sigs") or [])

    sent_second = False
    use_sticker = outcome == "W" and win_stickers and random.random() < 0.62
    use_sticker = use_sticker or (outcome == "L" and loss_stickers and random.random() < 0.62)

    if use_sticker:
        pool = win_stickers if outcome == "W" else loss_stickers
        st_id = _pick_from_pool_str(pool, recent_stickers, _STICKER_RING)
        await _chat_action(bot, channel_id, typing=typing_sim and typing_media, media=True)
        try:
            await bot.send_sticker(chat_id=channel_id, sticker=st_id)
            sent_second = True
            recent_stickers = _ring_push_str(recent_stickers, st_id, _STICKER_RING)
        except Exception as e:
            log.info("sticker send failed, will try image: %s", e)

    if not sent_second and result_images:
        await _chat_action(bot, channel_id, typing=typing_sim and typing_media, media=True)
        img = random.choice(result_images)
        img = dict(img)
        if captions and random.random() < 0.72:
            cap = _pick_from_pool_str(
                captions,
                recent_caps,
                _CAPTION_RING,
            )
            img["caption"] = cap
            recent_caps = _ring_push_str(
                recent_caps,
                hashlib.sha1(cap.encode()).hexdigest()[:16],
                _CAPTION_RING,
            )
        mid2 = await send_content_to_chat(bot, chat_id=channel_id, content=img, buttons_json=None)
        sent_second = bool(mid2)

    recent_set_ids = _ring_push_int(recent_set_ids, int(chosen.id), _SET_RING)
    recent_tmpl = _ring_push_str(recent_tmpl, tkey, 5)
    outcomes = list(state.get("recent_outcomes") or [])
    outcomes.append(outcome)
    outcomes = outcomes[-6:]

    seq = list(state.get("recent_sequences") or [])
    sig = f"{chosen.id}|{outcome}|{tkey}"
    seq.append(sig)
    seq = seq[-_SEQ_RING:]

    state.update(
        {
            "recent_set_ids": recent_set_ids,
            "recent_template_keys": recent_tmpl,
            "recent_sticker_ids": recent_stickers,
            "recent_caption_sigs": recent_caps,
            "recent_outcomes": outcomes,
            "recent_sequences": seq,
        }
    )
    st.state_json = state
    await session.flush()
    return True
