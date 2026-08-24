"""Vercel function: one-time setup from the browser (no local machine needed).

Visit:
    https://<app>.vercel.app/api/setup?token=<WEBHOOK_SECRET>

It will:
  1. Create the database tables (idempotent).
  2. Register the Telegram webhook -> <PUBLIC_BASE_URL>/api/webhook.
  3. Report the bot identity and webhook status.

Safe to run multiple times. Requires ?token=<WEBHOOK_SECRET>.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the project root importable from inside /api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app._aio import run_async  # noqa: E402


async def _run() -> dict:
    from app.config import settings

    out: dict = {"ok": True, "steps": {}}

    # 1) DB schema
    try:
        from app.db.base import init_db

        await init_db()
        out["steps"]["database"] = {"ok": True, "detail": "tables created / verified"}
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["steps"]["database"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    # 2) Webhook
    from aiogram import Bot

    bot = Bot(token=settings.bot_token)
    try:
        me = await bot.get_me()
        out["bot"] = {"username": me.username, "id": me.id}
        if not settings.public_base_url:
            out["ok"] = False
            out["steps"]["webhook"] = {"ok": False, "error": "PUBLIC_BASE_URL not set"}
        else:
            url = settings.public_base_url.rstrip("/") + "/api/webhook"
            await bot.set_webhook(
                url=url,
                secret_token=settings.webhook_secret or None,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "channel_post"],
            )
            info = await bot.get_webhook_info()
            out["steps"]["webhook"] = {
                "ok": bool(info.url),
                "url": info.url,
                "pending": info.pending_update_count,
                "last_error": info.last_error_message,
            }
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["steps"]["webhook"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    # 3) Menu button -> launches the Mini App from the chat input bar
    try:
        if settings.public_base_url:
            from aiogram.types import MenuButtonWebApp, WebAppInfo

            app_url = settings.public_base_url.rstrip("/") + "/app/"
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Open App", web_app=WebAppInfo(url=app_url))
            )
            out["steps"]["menu_button"] = {"ok": True, "app_url": app_url}
    except Exception as e:  # noqa: BLE001
        out["steps"]["menu_button"] = {"ok": False, "error": str(e)[:200]}

    # 4) Bot description ("What can this bot do?") + short description
    try:
        await bot.set_my_description(description=(
            "💵 Dollar Bumper — earn real USDT on Telegram.\n\n"
            "🚀 Complete quick tasks, invite friends, and get paid on-chain — "
            "no conditions.\n"
            "📢 Projects: feature your channel to real, engaged users.\n\n"
            "Tap Start to open the app 👇"
        ))
        await bot.set_my_short_description(short_description=(
            "Earn real USDT — tasks, referrals, instant on-chain withdrawals."
        ))
        out["steps"]["description"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        out["steps"]["description"] = {"ok": False, "error": str(e)[:200]}
    finally:
        await bot.session.close()

    out["next"] = "Message your bot /start. If it replies, you're live."
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            from app.config import settings

            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if not settings.webhook_secret or token != settings.webhook_secret:
                self._json(401, {"ok": False, "error": "unauthorized — append ?token=<WEBHOOK_SECRET>"})
                return
            result = run_async(_run())
            self._json(200 if result["ok"] else 503, result)
        except Exception as e:  # noqa: BLE001
            # Surface the real cause instead of a bare 500 crash page.
            self._json(500, {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-1500:],
            })

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
