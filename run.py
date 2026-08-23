"""Dollar Bumper — long-polling entrypoint (for always-on hosts).

    python run.py

For serverless (Vercel), use the api/ webhook + cron functions instead.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.base import init_db
from app.runtime import get_bot, get_dispatcher
from app.services.payouts import confirm_payouts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("dollar_bumper")


async def main() -> None:
    await init_db()

    bot = get_bot()
    dp = get_dispatcher()

    # Confirm broadcast payouts every 30s (post proof, notify, refund on revert).
    scheduler = AsyncIOScheduler()
    scheduler.add_job(confirm_payouts, "interval", seconds=30, args=[bot], max_instances=1)
    scheduler.start()

    me = await bot.get_me()
    log.info("Starting Dollar Bumper as @%s (id=%s)", me.username, me.id)
    log.info("Admins: %s | Proof channel: %s", settings.admin_ids, settings.proof_channel_id or "—")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")
