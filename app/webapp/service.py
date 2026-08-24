"""Mini App business logic — reuses the same services as the bot."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import Bot
from sqlalchemy import func, select

from app.config import settings
from app.constants import WithdrawalStatus
from app.db.base import Session
from app.db.models import Campaign, User, Withdrawal
from app.services.campaigns import active_campaigns_for
from app.services.earning import complete_task, get_or_create_user
from app.services.membership import is_member
from app.services.payouts import request_withdrawal
from app.utils.format import q, usdt
from app.utils.validators import is_valid_evm_address, to_checksum
from app.webapp.auth import WebAppUser

_bot_username: str | None = None


def _q(v) -> str:
    return str(q(v))


async def _referral_of(u: WebAppUser) -> int | None:
    sp = (u.start_param or "").strip()
    return int(sp) if sp.isdigit() else None


async def home_state(u: WebAppUser, bot: Bot, ip: str | None = None) -> dict:
    user = await get_or_create_user(u.id, u.username, u.first_name, await _referral_of(u))

    # Record device IP once, and flag if another account already used this IP.
    async with Session() as s:
        row = await s.get(User, u.id)
        if ip and not row.signup_ip:
            row.signup_ip = ip[:64]
            dup = await s.scalar(
                select(func.count(User.id)).where(
                    User.signup_ip == ip[:64], User.id != u.id, User.is_banned.is_(False)
                )
            )
            if dup and int(dup) > 0:
                row.flagged = True
            await s.commit()
        device_ok = not row.flagged

    async with Session() as s:
        invites = await s.scalar(
            select(func.count(User.id)).where(
                User.referred_by == u.id, User.referral_credited.is_(True)
            )
        )

    global _bot_username
    if _bot_username is None:
        _bot_username = (await bot.get_me()).username

    return {
        "ok": True,
        "user": {"id": user.id, "first_name": user.first_name, "username": user.username},
        "wallet": user.wallet_address,
        "balance": _q(user.balance),
        "total_earned": _q(user.total_earned),
        "referral_earned": _q(user.referral_earned),
        "invites": int(invites or 0),
        "is_admin": settings.is_admin(user.id),
        "device_ok": device_ok,
        "onboarded": bool(row.onboarded),
        "referral_link": f"https://t.me/{_bot_username}?start={user.id}",
        "config": {
            "referral_reward": _q(settings.referral_reward),
            "min_withdrawal": _q(settings.min_withdrawal),
            "review_threshold": _q(settings.review_threshold),
            "min_campaign_budget": _q(settings.min_campaign_budget),
            "network": "BEP20 (BSC)",
        },
    }


def _name(first, username) -> str:
    return (first or (("@" + username) if username else None) or "Bumper")[:24]


async def leaderboard(u: WebAppUser) -> dict:
    async with Session() as s:
        # Top referrers — by number of valid (credited) invites.
        inv = (
            select(User.referred_by.label("ref"), func.count().label("cnt"))
            .where(User.referred_by.is_not(None), User.referral_credited.is_(True))
            .group_by(User.referred_by)
            .subquery()
        )
        ref_rows = (await s.execute(
            select(User.id, User.first_name, User.username, inv.c.cnt, User.referral_earned)
            .join(inv, inv.c.ref == User.id)
            .order_by(inv.c.cnt.desc(), User.referral_earned.desc())
            .limit(30)
        )).all()

        # Top withdrawals — by all-time PAID amount.
        wd = (
            select(Withdrawal.user_id.label("uid"), func.sum(Withdrawal.amount).label("tot"))
            .where(Withdrawal.status == WithdrawalStatus.PAID.value)
            .group_by(Withdrawal.user_id)
            .subquery()
        )
        wd_rows = (await s.execute(
            select(User.id, User.first_name, User.username, wd.c.tot)
            .join(User, User.id == wd.c.uid)
            .order_by(wd.c.tot.desc())
            .limit(30)
        )).all()

    return {
        "ok": True,
        "top_referrers": [
            {"name": _name(r[1], r[2]), "invites": int(r[3] or 0),
             "earned": _q(r[4]), "me": r[0] == u.id}
            for r in ref_rows
        ],
        "top_withdrawals": [
            {"name": _name(r[1], r[2]), "total": _q(r[3]), "me": r[0] == u.id}
            for r in wd_rows
        ],
    }


async def channels_status(u: WebAppUser, bot: Bot) -> dict:
    """Required channels + whether the user has joined each."""
    result = []
    all_joined = True
    for ch in settings.required_channels:
        joined = await is_member(bot, ch, u.id)
        if not joined:
            all_joined = False
        result.append({
            "username": ch,
            "url": f"https://t.me/{ch.lstrip('@')}",
            "joined": joined,
        })
    return {"ok": True, "channels": result, "all_joined": all_joined}


async def complete_onboarding(u: WebAppUser, bot: Bot) -> dict:
    # Enforce channel membership server-side (not just in the UI).
    for ch in settings.required_channels:
        if not await is_member(bot, ch, u.id):
            return {"ok": False, "error": "Please join all channels first.", "need_channels": True}
    async with Session() as s:
        user = await s.get(User, u.id)
        if user is None:
            return {"ok": False, "error": "User not found."}
        user.onboarded = True
        await s.commit()
    return {"ok": True}


async def tasks_list(u: WebAppUser) -> dict:
    camps = await active_campaigns_for(u.id)
    return {
        "ok": True,
        "tasks": [
            {
                "id": c.id,
                "title": c.title,
                "channel": c.channel,
                "reward": _q(c.reward_per_task),
                "description": c.description,
                "url": f"https://t.me/{c.channel.lstrip('@')}",
            }
            for c in camps
        ],
    }


async def task_verify(u: WebAppUser, campaign_id: int, bot: Bot) -> dict:
    async with Session() as s:
        c = await s.get(Campaign, campaign_id)
    if c is None:
        return {"ok": False, "error": "Task not found."}
    if not await is_member(bot, c.channel, u.id):
        return {"ok": False, "error": f"Join {c.channel} first, then verify."}

    res = await complete_task(u.id, campaign_id)
    if not res.ok:
        return {"ok": False, "error": res.message}

    if res.referral_bonus_to:
        try:
            await bot.send_message(
                res.referral_bonus_to,
                f"🎉 A friend you invited completed a task — "
                f"<b>{usdt(res.referral_bonus_amount)}</b> added to your balance!",
            )
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "reward": _q(res.reward)}


async def set_wallet(u: WebAppUser, address: str) -> dict:
    address = (address or "").strip()
    if not is_valid_evm_address(address):
        return {"ok": False, "error": "That isn't a valid BEP20 address (0x + 40 hex)."}
    checksummed = to_checksum(address)
    await get_or_create_user(u.id, u.username, u.first_name, await _referral_of(u))
    async with Session() as s:
        user = await s.get(User, u.id)
        user.wallet_address = checksummed
        await s.commit()
    return {"ok": True, "wallet": checksummed}


async def withdraw(u: WebAppUser, amount, bot: Bot) -> dict:
    amt: Decimal | None
    if amount in (None, "", "all"):
        amt = None
    else:
        try:
            amt = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return {"ok": False, "error": "Enter a valid amount."}
    res = await request_withdrawal(u.id, amt, bot)
    return {"ok": res.ok, "message": res.message, "needs_review": res.needs_review}
