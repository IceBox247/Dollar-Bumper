"""Vercel function: health check for the deployment wiring.

Visit  https://<app>.vercel.app/api/health?token=<WEBHOOK_SECRET>
to confirm the DB, BSC RPC, and payout wallet are all reachable.
If WEBHOOK_SECRET is unset, no token is required.
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


async def _gather() -> dict:
    out: dict = {"ok": True, "checks": {}}

    # DB
    try:
        from sqlalchemy import func, select

        from app.db.base import Session, ensure_initialized
        from app.db.models import User

        await ensure_initialized()
        async with Session() as s:
            users = await s.scalar(select(func.count(User.id)))
        out["checks"]["database"] = {"ok": True, "users": int(users or 0)}
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["checks"]["database"] = {"ok": False, "error": str(e)[:200]}

    # Chain / payout wallet
    try:
        from app.services.chain import chain

        usdt_bal = await chain.payout_balance()
        bnb_bal = await chain.gas_balance()
        out["checks"]["chain"] = {
            "ok": True,
            "payout_wallet": settings.payout_wallet_address,
            "usdt": str(usdt_bal),
            "bnb_gas": f"{bnb_bal:.6f}",
            "low_gas": bnb_bal < 0.005,
        }
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["checks"]["chain"] = {"ok": False, "error": str(e)[:200]}

    out["config"] = {
        "proof_channel": settings.proof_channel_id or None,
        "required_channels": settings.required_channels,
        "min_withdrawal": str(settings.min_withdrawal),
        "review_threshold": str(settings.review_threshold),
    }
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if settings.webhook_secret:
            token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if token != settings.webhook_secret:
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
        try:
            result = asyncio.run(_gather())
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(e)[:200]})
            return
        self._json(200 if result["ok"] else 503, result)

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
