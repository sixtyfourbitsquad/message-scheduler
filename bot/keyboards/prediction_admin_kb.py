"""Inline keyboards for Telegram prediction-engine admin (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def pred_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📚 Sets", callback_data="pred:sets"),
                InlineKeyboardButton("⏰ Schedules", callback_data="pred:sch"),
            ],
            [
                InlineKeyboardButton("⏸️ Pause all engine", callback_data="pred:ps:all"),
                InlineKeyboardButton("▶️ Resume all engine", callback_data="pred:rs:all"),
            ],
            [InlineKeyboardButton("📈 Stats & logs", callback_data="pred:stats")],
            [InlineKeyboardButton("⬅️ Home", callback_data="m:home")],
        ]
    )


def pred_sets_list_kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    rows.append([InlineKeyboardButton("➕ New set", callback_data="pred:new"), InlineKeyboardButton("⬅️ Back", callback_data="pred:hub")])
    return InlineKeyboardMarkup(rows)


def pred_set_detail_kb(sid: int, active: bool, premium: bool) -> InlineKeyboardMarkup:
    act = "✅ Active" if active else "⏸️ Inactive"
    pr = "⭐ Premium" if premium else "○ Standard"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(act, callback_data=f"pred:at:{sid}"),
                InlineKeyboardButton(pr, callback_data=f"pred:pm:{sid}"),
            ],
            [
                InlineKeyboardButton("✏️ Name", callback_data=f"pred:ne:{sid}"),
                InlineKeyboardButton("⚖️ Weight", callback_data=f"pred:nw:{sid}"),
            ],
            [
                InlineKeyboardButton("➕ WIN sticker", callback_data=f"pred:wt:{sid}"),
                InlineKeyboardButton("➕ LOSS sticker", callback_data=f"pred:lt:{sid}"),
            ],
            [
                InlineKeyboardButton("➕ Template", callback_data=f"pred:tm:{sid}"),
                InlineKeyboardButton("➕ Result media", callback_data=f"pred:ri:{sid}"),
            ],
            [
                InlineKeyboardButton("➕ Caption", callback_data=f"pred:ca:{sid}"),
                InlineKeyboardButton("➕ Register line", callback_data=f"pred:rg:{sid}"),
            ],
            [InlineKeyboardButton("➕ Warning line", callback_data=f"pred:wr:{sid}")],
            [InlineKeyboardButton("🗑️ Delete set", callback_data=f"pred:dl:{sid}")],
            [InlineKeyboardButton("⬅️ Sets list", callback_data="pred:sets"), InlineKeyboardButton("🏠 Hub", callback_data="pred:hub")],
        ]
    )


def pred_set_delete_confirm_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes delete", callback_data=f"pred:dy:{sid}"),
                InlineKeyboardButton("⬅️ Cancel", callback_data=f"pred:set:{sid}"),
            ]
        ]
    )


def pred_schedules_kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    rows.append([InlineKeyboardButton("⬅️ Hub", callback_data="pred:hub")])
    return InlineKeyboardMarkup(rows)


def pred_schedule_engine_kb(sid: int, engine_on: bool) -> InlineKeyboardMarkup:
    eng = "🔴 Turn engine OFF" if engine_on else "🟢 Turn engine ON"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(eng, callback_data=f"pred:eg:{sid}")],
            [
                InlineKeyboardButton("⏱️ Delays & random", callback_data=f"pred:op:{sid}"),
                InlineKeyboardButton("🧪 Test run", callback_data=f"pred:try:{sid}"),
            ],
            [
                InlineKeyboardButton("⏸️ Pause schedule", callback_data=f"pred:zp:{sid}"),
                InlineKeyboardButton("▶️ Resume schedule", callback_data=f"pred:zr:{sid}"),
            ],
            [InlineKeyboardButton("⬅️ Schedules", callback_data="pred:sch"), InlineKeyboardButton("🏠 Hub", callback_data="pred:hub")],
        ]
    )


def pred_schedule_opts_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Min delay (sec)", callback_data=f"pred:dm:{sid}")],
            [InlineKeyboardButton("Max delay (sec)", callback_data=f"pred:dv:{sid}")],
            [InlineKeyboardButton("Register chance 0–1", callback_data=f"pred:rp:{sid}")],
            [InlineKeyboardButton("Warning chance 0–1", callback_data=f"pred:wp:{sid}")],
            [
                InlineKeyboardButton("Typing ON", callback_data=f"pred:ty1:{sid}"),
                InlineKeyboardButton("Typing OFF", callback_data=f"pred:ty0:{sid}"),
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"pred:sg:{sid}")],
        ]
    )


def pred_pool_remove_row(sid: int, label: str, cat: str, idx: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(f"🗑️ {label[:18]}", callback_data=f"pred:rm:{sid}:{cat}:{idx}")]


def pred_stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Refresh", callback_data="pred:stats"), InlineKeyboardButton("⬅️ Hub", callback_data="pred:hub")]])
