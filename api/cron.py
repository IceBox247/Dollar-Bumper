"""Vercel Cron function: finalize broadcast payouts (post proof, notify, refund).

Runs on the schedule in vercel.json. On Hobby this is once/day — payout
confirmation ALSO happens opportunistically on user traffic, so users don't
wait for cron. Upgrade the schedule on Pro for faster confirmation.
"""
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app._aio import run_async  # noqa: E402
from app.config import settings  # noqa: E402
from app.runtime import run_confirm  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        # Vercel injects `Authorization: Bearer <CRON_SECRET>` when CRON_SECRET is set.
        if settings.cron_secret:
            if self.headers.get("Authorization") != f"Bearer {settings.cron_secret}":
                self._respond(401, "unauthorized")
                return

        n = 0
        try:
            n = run_async(run_confirm(limit=50))
        except Exception as e:  # noqa: BLE001
            print("cron error:", repr(e))
            self._respond(500, "error")
            return
        self._respond(200, f"confirmed={n}")

    def _respond(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:
        return
