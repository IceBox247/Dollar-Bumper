"""Vercel function: read Telegram's webhook status WITHOUT changing anything.

    https://<app>.vercel.app/api/diag?token=<WEBHOOK_SECRET>

Shows the last delivery error Telegram saw — the fastest way to learn why the
bot isn't replying (e.g. the webhook function is 500ing or timing out).
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app._aio import run_async  # noqa: E402


async def _run() -> dict:
    from aiogram import Bot

    from app.config import settings

    bot = Bot(token=settings.bot_token)
    try:
        info = await bot.get_webhook_info()
        return {
            "ok": True,
            "webhook_url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_date": str(info.last_error_date) if info.last_error_date else None,
            "last_error_message": info.last_error_message,
            "last_synchronization_error_date": (
                str(info.last_synchronization_error_date)
                if getattr(info, "last_synchronization_error_date", None) else None
            ),
            "max_connections": info.max_connections,
            "ip_address": getattr(info, "ip_address", None),
            "has_custom_certificate": info.has_custom_certificate,
            "allowed_updates": info.allowed_updates,
        }
    finally:
        await bot.session.close()


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            from app.config import settings

            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if not settings.webhook_secret or token != settings.webhook_secret:
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(200, run_async(_run()))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}",
                             "trace": traceback.format_exc()[-1200:]})

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
