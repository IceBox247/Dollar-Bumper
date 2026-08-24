"""Helpers shared by the Mini App API function."""
from __future__ import annotations

import json

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings

_bot: Bot | None = None


def get_bot() -> Bot:
    """A bare aiogram Bot (no dispatcher/handlers) for API-side Telegram calls."""
    global _bot
    if _bot is None:
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def read_json_body(rfile, headers) -> dict:
    length = int(headers.get("content-length") or 0)
    raw = rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw or b"{}")
    except Exception:  # noqa: BLE001
        return {}
