"""Inline keyboard builders for the private control panel (no slash menus)."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def kb_main_menu() -> InlineKeyboardMarkup:
    """🏠 CHANNEL CONTROL PANEL — root dashboard."""
    rows = [
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="m:bc"),
            InlineKeyboardButton("⏰ Scheduler", callback_data="m:sch"),
        ],
        [
            InlineKeyboardButton("📂 Scheduled Posts", callback_data="m:lst"),
            InlineKeyboardButton("⚙️ Settings", callback_data="m:cfg"),
        ],
        [
            InlineKeyboardButton("💬 /start message", callback_data="m:sr"),
            InlineKeyboardButton("📊 Statistics", callback_data="m:st"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def kb_back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Back", callback_data="m:home"),
                InlineKeyboardButton("❌ Close", callback_data="m:x"),
            ]
        ]
    )


def kb_broadcast_entry() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Start broadcast wizard", callback_data="bc:start")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m:home")],
        ]
    )


def kb_yes_no_skip(*, yes_data: str, no_data: str, cancel_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data=yes_data),
                InlineKeyboardButton("⏭️ Skip", callback_data=no_data),
            ],
            [InlineKeyboardButton("⬅️ Cancel flow", callback_data=cancel_data)],
        ]
    )


def kb_broadcast_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📣 Channel only", callback_data="bc:send:ch"),
                InlineKeyboardButton("📣+💬 Channel + DMs", callback_data="bc:send:both"),
            ],
            [InlineKeyboardButton("💬 Subscribers (DM only)", callback_data="bc:send:dm")],
            [
                InlineKeyboardButton("⏰ Schedule", callback_data="bc:queue_sch"),
                InlineKeyboardButton("❌ Cancel", callback_data="bc:cancel"),
            ],
        ]
    )


def kb_start_reply_hub() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Edit message & buttons", callback_data="sr:start")],
            [InlineKeyboardButton("🔛 Toggle enabled", callback_data="sr:toggle")],
            [InlineKeyboardButton("📩 Test saved message", callback_data="sr:test")],
            [InlineKeyboardButton("🧹 Clear & disable", callback_data="sr:clear")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m:home")],
        ]
    )


def kb_start_reply_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💾 Save & enable", callback_data="sr:save")],
            [InlineKeyboardButton("📩 Test draft", callback_data="sr:test")],
            [InlineKeyboardButton("❌ Cancel", callback_data="sr:cancel")],
        ]
    )


def kb_scheduler_entry() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧩 New scheduled post", callback_data="sch:start")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m:home")],
        ]
    )


def kb_schedule_kind() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1️⃣ One-time", callback_data="sch:k:once")],
            [InlineKeyboardButton("🔁 Daily (one time of day)", callback_data="sch:k:daily")],
            [
                InlineKeyboardButton(
                    "🇮🇳 Daily ×6 IST peaks",
                    callback_data="sch:k:daily_peak",
                )
            ],
            [InlineKeyboardButton("📅 Weekly", callback_data="sch:k:weekly")],
            [InlineKeyboardButton("⏱️ Custom interval", callback_data="sch:k:interval")],
            [InlineKeyboardButton("⬅️ Cancel", callback_data="sch:cancel")],
        ]
    )


def kb_schedule_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💾 Save schedule", callback_data="sch:save")],
            [InlineKeyboardButton("❌ Cancel", callback_data="sch:cancel")],
        ]
    )


def kb_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📣 Target channel", callback_data="cfg:ch")],
            [InlineKeyboardButton("💬 Discussion group", callback_data="cfg:dg")],
            [InlineKeyboardButton("🌐 Timezone", callback_data="cfg:tz")],
            [InlineKeyboardButton("🪵 Toggle logs", callback_data="cfg:log")],
            [InlineKeyboardButton("🩺 Bot status", callback_data="cfg:status")],
            [InlineKeyboardButton("🔁 Restart scheduler", callback_data="cfg:rsch")],
            [InlineKeyboardButton("🗄️ DB health", callback_data="cfg:db")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m:home")],
        ]
    )


def kb_stats_refresh() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 Refresh", callback_data="m:st")],
            [InlineKeyboardButton("⬅️ Back", callback_data="m:home")],
        ]
    )


def kb_posts_row(schedule_id: int) -> InlineKeyboardMarkup:
    sid = str(schedule_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✏️", callback_data=f"lst:e:{sid}"),
                InlineKeyboardButton("⏸️", callback_data=f"lst:p:{sid}"),
                InlineKeyboardButton("▶️", callback_data=f"lst:r:{sid}"),
                InlineKeyboardButton("🗑️", callback_data=f"lst:d:{sid}"),
            ],
            [InlineKeyboardButton("⬅️ Back to list", callback_data="m:lst")],
        ]
    )


def kb_confirm_delete(schedule_id: int) -> InlineKeyboardMarkup:
    sid = str(schedule_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm delete", callback_data=f"lst:dd:{sid}"),
                InlineKeyboardButton("⬅️ Back", callback_data=f"lst:v:{sid}"),
            ]
        ]
    )


def kb_button_builder_controls() -> InlineKeyboardMarkup:
    """During URL button collection for broadcast/scheduler."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ New row", callback_data="btn:newrow")],
            [InlineKeyboardButton("✅ Done", callback_data="btn:done")],
            [InlineKeyboardButton("⬅️ Cancel", callback_data="btn:cancel")],
        ]
    )
