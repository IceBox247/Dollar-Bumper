"""Router registration."""
from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers import (
    admin,
    advertiser,
    menu,
    referral,
    start,
    tasks,
    wallet,
    withdraw,
)


def register_handlers(dp: Dispatcher) -> None:
    # Order matters: the menu guard runs first so reply-keyboard buttons and
    # /cancel always break out of an in-progress flow; then specific routers,
    # then the catch-all in start.
    dp.include_router(menu.router)
    dp.include_router(admin.router)
    dp.include_router(wallet.router)
    dp.include_router(tasks.router)
    dp.include_router(referral.router)
    dp.include_router(withdraw.router)
    dp.include_router(advertiser.router)
    dp.include_router(start.router)  # includes gate + menu fallbacks
