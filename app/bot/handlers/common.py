"""Shared helpers for handlers (join-gate, referral link)."""
from __future__ import annotations

from aiogram import Bot

from app.config import settings
from app.services.membership import is_member, member_status


async def missing_channels(bot: Bot, user_id: int) -> list[str]:
    """Return required channels the user has NOT joined."""
    missing: list[str] = []
    for ch in settings.required_channels:
        if not await is_member(bot, ch, user_id):
            missing.append(ch)
    return missing


async def missing_channels_detailed(bot: Bot, user_id: int) -> list[tuple[str, str]]:
    """Return [(channel, reason)] for channels NOT joined — reason names the
    status or the error (an error usually means the bot isn't admin there)."""
    out: list[tuple[str, str]] = []
    for ch in settings.required_channels:
        joined, reason = await member_status(bot, ch, user_id)
        if not joined:
            out.append((ch, reason))
    return out


async def referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start={user_id}"
