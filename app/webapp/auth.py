"""Validate Telegram Mini App initData.

Every API request from the Mini App sends the raw `initData` string Telegram
provides to the web page. We verify its HMAC signature with the bot token so a
request can be trusted to come from a real Telegram user, and extract that
user's id/profile.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.config import settings


@dataclass
class WebAppUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    start_param: str | None = None


class AuthError(Exception):
    pass


def _secret_key() -> bytes:
    # secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    return hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(init_data: str, max_age_seconds: int = 86400) -> WebAppUser:
    """Verify initData and return the authenticated user. Raises AuthError."""
    if not init_data:
        raise AuthError("missing initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("missing hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    calc = hmac.new(_secret_key(), data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise AuthError("bad signature")

    # Freshness check (guards against replay of old initData).
    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit():
        if max_age_seconds and (time.time() - int(auth_date)) > max_age_seconds:
            raise AuthError("initData expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise AuthError("no user in initData")
    try:
        u = json.loads(user_raw)
    except Exception as e:  # noqa: BLE001
        raise AuthError("bad user json") from e

    return WebAppUser(
        id=int(u["id"]),
        first_name=u.get("first_name"),
        last_name=u.get("last_name"),
        username=u.get("username"),
        start_param=pairs.get("start_param"),
    )
