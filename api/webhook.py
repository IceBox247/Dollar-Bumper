"""Vercel serverless function: Telegram webhook endpoint.

Telegram POSTs updates here. Set the webhook to:
    https://<your-app>.vercel.app/api/webhook
with a secret_token equal to WEBHOOK_SECRET (see scripts/set_webhook.py).
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the project root importable from inside /api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app._aio import run_async  # noqa: E402
from app.config import settings  # noqa: E402
from app.runtime import process_update  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        # Verify Telegram's secret token header.
        if settings.webhook_secret:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if got != settings.webhook_secret:
                self._respond(401, "unauthorized")
                return

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._respond(400, "bad json")
            return

        try:
            run_async(process_update(data))
        except Exception as e:  # noqa: BLE001
            # Always 200 so Telegram doesn't spin on retries; log for debugging.
            print("webhook error:", repr(e))

        self._respond(200, "ok")

    def do_GET(self) -> None:  # noqa: N802
        self._respond(200, "Dollar Bumper webhook is up.")

    def _respond(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:  # silence default noisy logging
        return
