"""Vercel function: lightweight keep-alive.

Hitting this every ~2 minutes keeps Neon's free database awake (it auto-suspends
after 5 min idle), so real webhook taps never wait for a cold DB wake and stay
well under the serverless timeout. No auth needed — it only runs `SELECT 1`.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _ping() -> dict:
    from sqlalchemy import text

    from app.db.base import Session

    async with Session() as s:
        await s.execute(text("SELECT 1"))
    return {"ok": True, "ts": int(time.time())}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            body = asyncio.run(_ping())
            code = 200
        except Exception as e:  # noqa: BLE001
            body, code = {"ok": False, "error": str(e)[:200]}, 500
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
