"""
Post serialized `content_json` payloads to a Telegram channel.

Centralizes send logic for broadcasts and scheduled posts (including subscriber DMs).
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import Bot
from telegram.error import TelegramError

from bot.utils.inline_keyboard_json import rows_from_json
from bot.utils.message_serialize import entities_from_storage

log = logging.getLogger(__name__)


def _caption_entity_kwargs(content: dict[str, Any]) -> dict[str, Any]:
    ce = entities_from_storage(content.get("caption_entities"))
    return {"caption_entities": ce} if ce else {}


async def send_content_to_chat(
    bot: Bot,
    *,
    chat_id: int,
    content: dict[str, Any],
    buttons_json: list[list[dict[str, str]]] | None = None,
    reply_to_message_id: int | None = None,
) -> int | None:
    """
    Send payload to `chat_id`. Returns message_id on success, None on unsupported/failure.

    Uses `file_id` resend pattern — IDs can expire for some media; handle errors upstream.
    """
    markup = rows_from_json(buttons_json)
    ctype = content.get("type")
    thread_kw: dict[str, Any] = {}
    if reply_to_message_id is not None:
        thread_kw["reply_to_message_id"] = reply_to_message_id

    try:
        if ctype == "text":
            ents = entities_from_storage(content.get("entities"))
            try:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=content["text"],
                    reply_markup=markup,
                    entities=ents,
                    **thread_kw,
                )
            except Exception:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=content["text"],
                    reply_markup=markup,
                    **thread_kw,
                )
            return msg.message_id
        if ctype == "photo":
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "video":
            msg = await bot.send_video(
                chat_id=chat_id,
                video=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "animation":
            msg = await bot.send_animation(
                chat_id=chat_id,
                animation=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "document":
            msg = await bot.send_document(
                chat_id=chat_id,
                document=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                filename=content.get("filename"),
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "audio":
            msg = await bot.send_audio(
                chat_id=chat_id,
                audio=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "voice":
            msg = await bot.send_voice(
                chat_id=chat_id,
                voice=content["file_id"],
                caption=content.get("caption"),
                reply_markup=markup,
                **_caption_entity_kwargs(content),
                **thread_kw,
            )
            return msg.message_id
        if ctype == "unsupported":
            log.info("Unsupported content attempted: %s", content)
            return None
    except TelegramError as e:
        log.exception("send_content_to_chat failed: %s", e)
        raise

    log.warning("Unknown content type: %s", ctype)
    return None
