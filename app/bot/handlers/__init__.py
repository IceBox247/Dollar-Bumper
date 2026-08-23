"""Router registration."""
from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers import (
    admin,
    advertiser,
    referral,
    start,
    tasks,
    wallet,
    withdraw,
)


def register_handlers(dp: Dispatcher) -> None:
    # Order matters: specific routers before the catch-all in start.
    dp.include_router(admin.router)
    dp.include_router(wallet.router)
    dp.include_router(tasks.router)
    dp.include_router(referral.router)
    dp.include_router(withdraw.router)
    dp.include_router(advertiser.router)
    dp.include_router(start.router)  # includes gate + menu fallbacks
