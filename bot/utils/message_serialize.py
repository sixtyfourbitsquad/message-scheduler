"""
Serialize incoming `telegram.Message` into JSON-friendly dict for PostgreSQL JSONB.

We store Telegram `file_id` values so the bot can resend later without keeping
the original private chat message around.
"""

from __future__ import annotations

from typing import Any

from telegram import Message, MessageEntity


def message_to_content_dict(message: Message) -> dict[str, Any]:
    """
    Map a user/admin message to a normalized payload used by posting services.

    Supported: text, photo, video, animation, document, audio, voice, video_note (as video),
    caption on media types.
    """
    if message.text and not message.photo:
        return {"type": "text", "text": message.text, "entities": _entities(message)}

    caption = message.caption
    cap_entities = message.caption_entities

    if message.photo:
        photo = message.photo[-1]
        return {
            "type": "photo",
            "file_id": photo.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
        }
    if message.video:
        return {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
        }
    if message.animation:
        return {
            "type": "animation",
            "file_id": message.animation.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
        }
    if message.document:
        return {
            "type": "document",
            "file_id": message.document.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
            "filename": message.document.file_name,
        }
    if message.audio:
        return {
            "type": "audio",
            "file_id": message.audio.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
        }
    if message.voice:
        return {
            "type": "voice",
            "file_id": message.voice.file_id,
            "caption": caption,
            "caption_entities": _entities_list(cap_entities),
        }

    # Unsupported for channel automation
    return {
        "type": "unsupported",
        "hint": "Send text, photo, video, GIF, document, audio, or voice.",
    }


def _entities(message: Message) -> list[dict[str, Any]] | None:
    return _entities_list(message.entities)


def _entities_list(entities) -> list[dict[str, Any]] | None:
    if not entities:
        return None
    out = []
    for e in entities:
        d = {"type": e.type, "offset": e.offset, "length": e.length}
        if e.url:
            d["url"] = e.url
        if e.user:
            d["user_id"] = e.user.id
        if e.language:
            d["language"] = e.language
        if e.custom_emoji_id:
            d["custom_emoji_id"] = e.custom_emoji_id
        out.append(d)
    return out


def entities_from_storage(data: list[dict[str, Any]] | None) -> tuple[MessageEntity, ...] | None:
    """Rebuild PTB `MessageEntity` objects from JSON stored in PostgreSQL."""
    if not data:
        return None
    out: list[MessageEntity] = []
    for x in data:
        try:
            out.append(
                MessageEntity(
                    type=x["type"],
                    offset=int(x["offset"]),
                    length=int(x["length"]),
                    url=x.get("url"),
                    language=x.get("language"),
                    custom_emoji_id=x.get("custom_emoji_id"),
                )
            )
        except Exception:
            continue
    return tuple(out) if out else None
