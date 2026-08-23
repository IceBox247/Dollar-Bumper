"""Shared helpers for handlers (join-gate, referral link)."""
from __future__ import annotations

from aiogram import Bot

from app.config import settings
from app.services.membership import is_member


async def missing_channels(bot: Bot, user_id: int) -> list[str]:
    """Return required channels the user has NOT joined."""
    missing: list[str] = []
    for ch in settings.required_channels:
        if not await is_member(bot, ch, user_id):
            missing.append(ch)
    return missing


async def referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start={user_id}"
