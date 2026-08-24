"""Vercel function: run a synthetic /start through the dispatcher and report
any exception — the fastest way to catch a handler error the webhook swallows.

    https://<app>.vercel.app/api/testupdate?token=<WEBHOOK_SECRET>

If it works, the admin will actually receive the /start reply in Telegram.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BUILD = "menu-routing-fix-438cc73"

# Map easy URL keywords -> the real reply-keyboard button text.
_BUTTONS = {
    "wallet": "💼 Wallet",
    "tasks": "📋 Earn Tasks",
    "invite": "👥 Invite & Earn",
    "withdraw": "💸 Withdraw",
    "advertise": "📢 Advertise",
    "help": "ℹ️ Help",
    "start": "/start",
}


async def _run(text_key: str) -> dict:
    from aiogram.types import Update

    from app.config import settings
    from app.db.base import ensure_initialized
    from app.runtime import get_bot, get_dispatcher

    if not settings.admin_ids:
        return {"ok": False, "build": BUILD, "error": "No ADMIN_IDS configured."}

    text = _BUTTONS.get(text_key.lower(), "/start")
    is_cmd = text.startswith("/")

    await ensure_initialized()
    bot, dp = get_bot(), get_dispatcher()
    uid = settings.admin_ids[0]

    msg: dict = {
        "message_id": int(time.time()) % 100000,
        "date": int(time.time()),
        "chat": {"id": uid, "type": "private", "first_name": "Admin"},
        "from": {"id": uid, "is_bot": False, "first_name": "Admin", "username": "admin"},
        "text": text,
    }
    if is_cmd:
        msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]

    update = Update.model_validate({"update_id": int(time.time()), "message": msg},
                                  context={"bot": bot})
    await dp.feed_update(bot, update)
    return {
        "ok": True,
        "build": BUILD,
        "simulated_text": text,
        "detail": f"Processed '{text}' for admin {uid}. Check Telegram for the reply.",
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            from app.config import settings

            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if not settings.webhook_secret or token != settings.webhook_secret:
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            text_key = parse_qs(urlparse(self.path).query).get("text", ["start"])[0]
            self._json(200, asyncio.run(_run(text_key)))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}",
                             "trace": traceback.format_exc()[-1800:]})

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
