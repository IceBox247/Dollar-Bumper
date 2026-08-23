"""Shared bot/dispatcher runtime, used by the webhook and cron functions."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.bot.handlers import register_handlers
from app.bot.storage import SQLAlchemyStorage
from app.config import settings
from app.db.base import ensure_initialized

log = logging.getLogger(__name__)

_bot: Bot | None = None
_dp: Dispatcher | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dp
    if _dp is None:
        _dp = Dispatcher(storage=SQLAlchemyStorage())
        register_handlers(_dp)
    return _dp


async def process_update(data: dict) -> None:
    """Handle one Telegram update (webhook payload)."""
    await ensure_initialized()
    bot, dp = get_bot(), get_dispatcher()

    # Piggyback payout confirmation on traffic (cheap when nothing is pending).
    try:
        from app.services.payouts import confirm_payouts

        await confirm_payouts(bot, limit=3)
    except Exception:  # noqa: BLE001
        log.exception("opportunistic confirm failed")

    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)


async def run_confirm(limit: int = 50) -> int:
    """Finalize broadcast payouts (called by cron)."""
    await ensure_initialized()
    from app.services.payouts import confirm_payouts

    return await confirm_payouts(get_bot(), limit=limit)
