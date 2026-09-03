"""Gamified 'Bumps' points: Lucky Wheel spins, watch-to-earn ads, arcade game,
and converting points to withdrawable USDT."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import settings
from app.db.base import Session
from app.db.models import User
from app.utils.format import q


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def points_to_usdt(points: int) -> Decimal:
    rate = settings.points_per_usdt or 10000
    return q(Decimal(points) / Decimal(rate))


@dataclass
class Result:
    ok: bool
    message: str = ""
    points: int = 0            # points delta or awarded
    balance_points: int = 0    # user's new points balance
    extra: dict | None = None


async def _get(s, user_id: int) -> User | None:
    return await s.get(User, user_id)


async def spin(user_id: int) -> Result:
    """Free Lucky Wheel spin every `spin_cooldown_hours`. Awards Bumps."""
    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=settings.spin_cooldown_hours)
    async with Session() as s:
        u = await _get(s, user_id)
        if u is None:
            return Result(False, "User not found.")
        if u.is_banned:
            return Result(False, "Your account is restricted.")
        last = u.last_spin_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            ready = last + cooldown
            if now < ready:
                mins = int((ready - now).total_seconds() // 60)
                return Result(False, f"Next free spin in ~{mins // 60}h {mins % 60}m.",
                              extra={"next_in_sec": int((ready - now).total_seconds())})
        reward = int(random.choice(settings.spin_rewards))
        u.points = int(u.points or 0) + reward
        u.last_spin_at = now
        new_points = u.points
        await s.commit()
    return Result(True, f"You won {reward} Bumps!", points=reward, balance_points=new_points,
                  extra={"next_in_sec": int(cooldown.total_seconds())})


async def claim_ad(user_id: int, network: str) -> Result:
    """Award Bumps for watching an ad, respecting the per-network daily cap."""
    network = (network or "").lower()
    if network == "adsgram":
        reward, cap = settings.ad_reward_adsgram, settings.ad_daily_adsgram
    elif network == "monetag":
        reward, cap = settings.ad_reward_monetag, settings.ad_daily_monetag
    else:
        return Result(False, "Unknown ad network.")
    today = _today()
    async with Session() as s:
        u = await _get(s, user_id)
        if u is None:
            return Result(False, "User not found.")
        if u.is_banned:
            return Result(False, "Your account is restricted.")
        if u.ad_day != today:  # new day → reset counters
            u.ad_day = today
            u.ad_count_adsgram = 0
            u.ad_count_monetag = 0
        used = u.ad_count_adsgram if network == "adsgram" else u.ad_count_monetag
        if used >= cap:
            return Result(False, "You've claimed all of today's ads for this network. Come back tomorrow!")
        if network == "adsgram":
            u.ad_count_adsgram = used + 1
        else:
            u.ad_count_monetag = used + 1
        u.points = int(u.points or 0) + reward
        new_points, left = u.points, cap - (used + 1)
        await s.commit()
    return Result(True, f"+{reward} Bumps!", points=reward, balance_points=new_points,
                  extra={"left_today": left})


async def game_reward(user_id: int, score: int) -> Result:
    """Award Bumps for an arcade game session — capped per round AND per day so
    users can't farm unlimited free points."""
    try:
        score = max(0, int(score))
    except (TypeError, ValueError):
        return Result(False, "Bad score.")
    reward = min(score * max(1, settings.game_reward_points), settings.game_reward_cap)
    today = _today()
    async with Session() as s:
        u = await _get(s, user_id)
        if u is None:
            return Result(False, "User not found.")
        if u.is_banned:
            return Result(False, "Your account is restricted.")
        if u.game_day != today:  # new day → reset the play counter
            u.game_day = today
            u.game_plays = 0
        if int(u.game_plays or 0) >= settings.game_daily_plays:
            return Result(False, "You've used all your game rounds for today. Come back tomorrow! ⏳",
                          balance_points=int(u.points or 0), extra={"plays_left": 0})
        u.game_plays = int(u.game_plays or 0) + 1
        u.points = int(u.points or 0) + reward
        new_points, left = u.points, settings.game_daily_plays - u.game_plays
        await s.commit()
    return Result(True, f"+{reward} Bumps!", points=reward, balance_points=new_points,
                  extra={"plays_left": left})


# Platforms a user can link. key -> friendly label.
SOCIAL_PLATFORMS = {
    "x": "X (Twitter)",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "facebook": "Facebook",
}


def _clean_handle(v) -> str:
    """Normalize a submitted handle/URL to a short, safe string (or '')."""
    s = str(v or "").strip()
    if not s:
        return ""
    s = s.replace("http://", "").replace("https://", "").strip().strip("<>")
    return s[:80]


def load_socials(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


async def save_socials(user_id: int, socials: dict) -> Result:
    """Store the user's social handles. Awards Bumps once per distinct platform
    they link (so adding a new platform later still pays out)."""
    incoming = {}
    for key, val in (socials or {}).items():
        k = str(key or "").strip().lower()
        if k not in SOCIAL_PLATFORMS:
            continue
        handle = _clean_handle(val)
        if handle:
            incoming[k] = handle
    async with Session() as s:
        u = await _get(s, user_id)
        if u is None:
            return Result(False, "User not found.")
        if u.is_banned:
            return Result(False, "Your account is restricted.")
        current = load_socials(u.socials)
        current.update(incoming)               # merge (keep old, overwrite edited)
        distinct = len(current)
        already = int(u.social_reward_count or 0)
        newly = max(0, distinct - already)
        award = newly * max(0, settings.social_reward_points)
        u.socials = json.dumps(current)
        u.social_reward_count = distinct
        if award:
            u.points = int(u.points or 0) + award
        new_points = u.points
        await s.commit()
    msg = (f"Saved! +{award} Bumps for linking your socials 🎉"
           if award else "Socials updated ✅")
    return Result(True, msg, points=award, balance_points=new_points,
                  extra={"socials": current, "linked": distinct})


async def convert_points(user_id: int, amount: int | None = None) -> Result:
    """Convert Bumps → withdrawable USDT balance at points_per_usdt."""
    rate = settings.points_per_usdt or 10000
    async with Session() as s:
        u = await _get(s, user_id)
        if u is None:
            return Result(False, "User not found.")
        have = int(u.points or 0)
        want = have if amount in (None, 0) else min(int(amount), have)
        if want < settings.min_points_convert:
            return Result(False, f"Need at least {settings.min_points_convert} Bumps to convert.")
        usdt = points_to_usdt(want)  # rounded to 6dp
        if usdt <= 0:
            return Result(False, f"Need at least {rate} Bumps to make 1 USDT.")
        u.points = have - want
        u.balance = q(u.balance + usdt)
        u.total_earned = q(u.total_earned + usdt)
        new_points = u.points
        await s.commit()
    return Result(True, f"Converted {want} Bumps → {usdt} USDT.", points=-want,
                  balance_points=new_points, extra={"usdt": str(usdt)})
