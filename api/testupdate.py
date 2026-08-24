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


async def _run() -> dict:
    from aiogram.types import Update

    from app.config import settings
    from app.db.base import ensure_initialized
    from app.runtime import get_bot, get_dispatcher

    if not settings.admin_ids:
        return {"ok": False, "error": "No ADMIN_IDS configured to test with."}

    await ensure_initialized()
    bot, dp = get_bot(), get_dispatcher()
    uid = settings.admin_ids[0]

    payload = {
        "update_id": int(time.time()),
        "message": {
            "message_id": int(time.time()) % 100000,
            "date": int(time.time()),
            "chat": {"id": uid, "type": "private", "first_name": "Admin"},
            "from": {"id": uid, "is_bot": False, "first_name": "Admin", "username": "admin"},
            "text": "/start",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }
    update = Update.model_validate(payload, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {
        "ok": True,
        "detail": f"/start processed for admin {uid}. Check Telegram — you should "
                  "have received the welcome/gate message.",
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            from app.config import settings

            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if not settings.webhook_secret or token != settings.webhook_secret:
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(200, asyncio.run(_run()))
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
