"""Vercel function: the Mini App API (single dispatch endpoint).

POST /api/app  with JSON body:
    { "action": "home|tasks|verify|set_wallet|withdraw", "initData": "<tg>", ... }

Every call is authenticated by verifying Telegram's initData signature.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Process-global throttle for the opportunistic payout confirmation. Module
# globals persist across warm invocations, so this bounds the on-chain work to
# at most one sweep per _CONFIRM_EVERY seconds for the WHOLE warm instance —
# instead of firing (and doing up to 5 BSC RPC calls) on every user's home load.
_last_confirm = 0.0
_CONFIRM_EVERY = 30.0  # seconds


async def _dispatch(action: str, data: dict, ip: str | None = None) -> dict:
    from app.db.base import ensure_initialized
    from app.webapp import service
    from app.webapp.api import get_bot
    from app.webapp.auth import AuthError, verify_init_data

    try:
        user = verify_init_data(data.get("initData", ""))
    except AuthError as e:
        return {"ok": False, "error": f"auth: {e}", "_status": 401}

    await ensure_initialized()
    bot = get_bot()

    if action == "home":
        # Opportunistically finalize any broadcast payouts so "Paid ✅" lands
        # without waiting for the daily cron — but throttled process-globally so
        # it runs at most once per _CONFIRM_EVERY seconds no matter how many
        # users hit home. (Trade-off: a just-paid tx may show "Paid" up to
        # ~30s later than before; the cron is the backstop.)
        global _last_confirm
        now = time.monotonic()
        if now - _last_confirm >= _CONFIRM_EVERY:
            _last_confirm = now
            try:
                from app.services.payouts import confirm_payouts

                await confirm_payouts(bot, limit=5)
            except Exception as e:  # noqa: BLE001
                print("opportunistic confirm error:", repr(e))
        return await service.home_state(user, bot, ip)
    if action == "channels":
        return await service.channels_status(user, bot)
    if action == "onboard":
        return await service.complete_onboarding(user, bot)
    if action == "leaderboard":
        return await service.leaderboard(user)
    if action == "tasks":
        return await service.tasks_list(user)
    if action == "verify":
        return await service.task_verify(user, int(data["campaign_id"]), bot)
    if action == "set_wallet":
        return await service.set_wallet(user, data.get("address", ""))
    if action == "withdraw":
        return await service.withdraw(user, data.get("amount"), bot)
    if action == "adv_list":
        return await service.advertise_list(user)
    if action == "adv_create":
        return await service.advertise_create(
            user, data.get("title", ""), data.get("url", ""),
            data.get("reward"), data.get("budget"),
        )
    if action == "adv_verify":
        return await service.advertise_verify(user, data.get("campaign_id"), data.get("tx_hash", ""))
    if action == "spin":
        return await service.spin_wheel(user)
    if action == "ad_reward":
        return await service.ad_reward(user, data.get("network", ""))
    if action == "game_finish":
        return await service.game_finish(user, data.get("score"))
    if action == "convert_points":
        return await service.convert_points_action(user, data.get("amount"))
    if action == "save_socials":
        return await service.save_socials_action(user, data.get("socials"))
    return {"ok": False, "error": "unknown action", "_status": 400}


class handler(BaseHTTPRequestHandler):
    def _client_ip(self) -> str | None:
        xff = self.headers.get("x-forwarded-for") or self.headers.get("x-real-ip") or ""
        return xff.split(",")[0].strip() or None if xff else None

    def do_POST(self) -> None:  # noqa: N802
        from app.webapp.api import read_json_body

        from app._aio import run_async

        data = read_json_body(self.rfile, self.headers)
        action = (data.get("action") or "").strip()
        try:
            result = run_async(_dispatch(action, data, self._client_ip()))
        except Exception as e:  # noqa: BLE001
            print("app api error:", repr(e))
            self._json(500, {"ok": False, "error": "server error"})
            return
        status = result.pop("_status", 200)
        self._json(status, result)

    def do_GET(self) -> None:  # noqa: N802
        self._json(200, {"ok": True, "service": "Dollar Bumper Mini App API"})

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, *args) -> None:
        return
