"""Build `InlineKeyboardMarkup` from stored JSON rows."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def rows_from_json(data: list[list[dict[str, str]]] | None) -> InlineKeyboardMarkup | None:
    """
    Convert JSON like [[{"text":"Go","url":"https://..."}], ...] to markup.

    Only `url` buttons are supported for channel posts (Telegram limitation for
    URL buttons on channel messages — text callbacks from channels are limited).
    """
    if not data:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in data:
        btns: list[InlineKeyboardButton] = []
        for cell in row:
            text = cell.get("text") or "Link"
            url = cell.get("url")
            if url:
                btns.append(InlineKeyboardButton(text=text, url=url))
        if btns:
            rows.append(btns)
    return InlineKeyboardMarkup(rows) if rows else None


def append_button_row(
    storage: list[list[dict[str, str]]],
    *,
    text: str,
    url: str,
    new_row: bool,
) -> None:
    """Mutate `storage` to add a button, optionally starting a new row."""
    if new_row or not storage:
        storage.append([])
    storage[-1].append({"text": text, "url": url})


def validate_http_url(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith("http://") or u.startswith("https://")
