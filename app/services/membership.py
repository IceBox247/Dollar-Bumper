"""Verify Telegram channel membership (for task completion & join gates)."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger(__name__)

_JOINED = {"member", "administrator", "creator"}


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
