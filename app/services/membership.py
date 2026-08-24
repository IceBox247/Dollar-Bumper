"""Verify Telegram channel membership (for task completion & join gates)."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger(__name__)

_JOINED = {"member", "administrator", "creator"}


async def member_status(bot: Bot, channel: str, user_id: int) -> tuple[bool, str]:
    """Return (joined, reason). reason is the status or an error string —
    an error usually means the bot isn't an admin of that channel."""
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in _JOINED, str(member.status)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:70]}"


async def bot_can_verify(bot: Bot, channel: str) -> bool:
    """True if the bot is an admin of `channel` (so it can check memberships)."""
    try:
        me = await bot.get_chat_member(chat_id=channel, user_id=(await bot.me()).id)
        return me.status in {"administrator", "creator"}
    except Exception:  # noqa: BLE001
        return False


async def is_member(bot: Bot, channel: str, user_id: int) -> bool:
    """True if user_id is a member of `channel` (@username or -100... id).

    Returns False (not an error) when the bot cannot see the channel — the
    calling code should surface a friendly 'make sure the bot is admin' hint.
    """
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in _JOINED
    except TelegramBadRequest as e:
        log.warning("membership check failed for %s in %s: %s", user_id, channel, e)
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("membership check error for %s in %s: %s", user_id, channel, e)
        return False
