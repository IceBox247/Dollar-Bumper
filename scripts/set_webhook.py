"""Register (or delete) the Telegram webhook for the Vercel deployment.

Set PUBLIC_BASE_URL (e.g. https://dollar-bumper.vercel.app) and WEBHOOK_SECRET
in your environment / .env, then:

    python -m scripts.set_webhook          # set webhook -> <base>/api/webhook
    python -m scripts.set_webhook --delete # remove the webhook (for local polling)
"""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot

from app.config import settings


async def main() -> None:
    delete = "--delete" in sys.argv
    bot = Bot(token=settings.bot_token)
    try:
        if delete:
            await bot.delete_webhook(drop_pending_updates=True)
            print("🗑️  Webhook deleted. You can now run local polling (python run.py).")
            return
        if not settings.public_base_url:
            print("❌ Set PUBLIC_BASE_URL first (e.g. https://your-app.vercel.app).")
            return
        url = settings.public_base_url.rstrip("/") + "/api/webhook"
        await bot.set_webhook(
            url=url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "channel_post"],
        )
        info = await bot.get_webhook_info()
        print(f"✅ Webhook set to: {info.url}")
        if settings.webhook_secret:
            print("🔐 Secret token enabled.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
