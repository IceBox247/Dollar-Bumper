"""Vercel function: one-time setup from the browser (no local machine needed).

Visit:
    https://<app>.vercel.app/api/setup?token=<WEBHOOK_SECRET>

It will:
  1. Create the database tables (idempotent).
  2. Register the Telegram webhook -> <PUBLIC_BASE_URL>/api/webhook with the
     WEBHOOK_SECRET as the secret token.
  3. Report the bot identity and webhook status.

Safe to run multiple times. Requires ?token=<WEBHOOK_SECRET>.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402


async def _run() -> dict:
    out: dict = {"ok": True, "steps": {}}

    # 1) DB schema
    try:
        from app.db.base import init_db

        await init_db()
        out["steps"]["database"] = {"ok": True, "detail": "tables created / verified"}
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["steps"]["database"] = {"ok": False, "error": str(e)[:300]}

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
        out["steps"]["webhook"] = {"ok": False, "error": str(e)[:300]}
    finally:
        await bot.session.close()

    out["next"] = "Message your bot /start. If it replies, you're live. 🎉"
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if not settings.webhook_secret or token != settings.webhook_secret:
            self._json(401, {"ok": False, "error": "unauthorized — append ?token=<WEBHOOK_SECRET>"})
            return
        try:
            result = asyncio.run(_run())
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(e)[:300]})
            return
        self._json(200 if result["ok"] else 503, result)

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
