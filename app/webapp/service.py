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
from app.services.membership import is_member, member_status
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
            if dup and int(dup) >= settings.ip_flag_threshold:
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
    if not _bot_username:
        # Prefer a configured username (zero network); fall back to a cached
        # getMe. Never let a Telegram hiccup fail the whole home payload.
        _bot_username = settings.bot_username or None
        if not _bot_username:
            try:
                _bot_username = (await bot.get_me()).username
            except Exception:  # noqa: BLE001
                _bot_username = None

    from datetime import datetime, timedelta, timezone

    from app.services.rewards import points_to_usdt

    pts = int(row.points or 0)
    # Spin readiness
    spin_ready, spin_next = True, 0
    if row.last_spin_at is not None:
        last = row.last_spin_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        ready_at = last + timedelta(hours=settings.spin_cooldown_hours)
        now = datetime.now(timezone.utc)
        if now < ready_at:
            spin_ready = False
            spin_next = int((ready_at - now).total_seconds())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used_ag = row.ad_count_adsgram if row.ad_day == today else 0
    used_mt = row.ad_count_monetag if row.ad_day == today else 0

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
        "points": pts,
        "points_usd": _q(points_to_usdt(pts)),
        "referral_link": (
            f"https://t.me/{_bot_username}?start={user.id}" if _bot_username else ""
        ),
        "config": {
            "referral_reward": _q(settings.referral_reward),
            "min_withdrawal": _q(settings.min_withdrawal),
            "review_threshold": _q(settings.review_threshold),
            "min_campaign_budget": _q(settings.min_campaign_budget),
            "network": "BEP20 (BSC)",
        },
        "game": {
            "points_per_usdt": settings.points_per_usdt,
            "min_convert": settings.min_points_convert,
            "spin_cooldown_hours": settings.spin_cooldown_hours,
            "spin_rewards": settings.spin_rewards,
            "spin_ready": spin_ready,
            "spin_next_sec": spin_next,
            "game_reward_cap": settings.game_reward_cap,
            "ads": {
                "adsgram_block_id": settings.adsgram_block_id,
                "monetag_zone_id": settings.monetag_zone_id,
                "adsgram": {"reward": settings.ad_reward_adsgram,
                            "cap": settings.ad_daily_adsgram, "used": used_ag},
                "monetag": {"reward": settings.ad_reward_monetag,
                            "cap": settings.ad_daily_monetag, "used": used_mt},
            },
        },
    }


def _name(first, username) -> str:
    return (first or (("@" + username) if username else None) or "Bumper")[:24]


async def leaderboard(u: WebAppUser) -> dict:
    admin_ids = settings.admin_ids  # keep the project's own accounts off the board
    async with Session() as s:
        # Top referrers — by number of valid (credited) invites.
        inv = (
            select(User.referred_by.label("ref"), func.count().label("cnt"))
            .where(User.referred_by.is_not(None), User.referral_credited.is_(True))
            .group_by(User.referred_by)
            .subquery()
        )
        ref_stmt = (
            select(User.id, User.first_name, User.username, inv.c.cnt, User.referral_earned)
            .join(inv, inv.c.ref == User.id)
            .order_by(inv.c.cnt.desc(), User.referral_earned.desc())
            .limit(30)
        )
        if admin_ids:
            ref_stmt = ref_stmt.where(User.id.not_in(admin_ids))
        ref_rows = (await s.execute(ref_stmt)).all()

        # Top withdrawals — by all-time PAID amount.
        wd = (
            select(Withdrawal.user_id.label("uid"), func.sum(Withdrawal.amount).label("tot"))
            .where(Withdrawal.status == WithdrawalStatus.PAID.value)
            .group_by(Withdrawal.user_id)
            .subquery()
        )
        wd_stmt = (
            select(User.id, User.first_name, User.username, wd.c.tot)
            .join(User, User.id == wd.c.uid)
            .order_by(wd.c.tot.desc())
            .limit(30)
        )
        if admin_ids:
            wd_stmt = wd_stmt.where(User.id.not_in(admin_ids))
        wd_rows = (await s.execute(wd_stmt)).all()

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

    credited_to: int | None = None
    credited_amt = q(settings.referral_reward)
    async with Session() as s:
        user = await s.get(User, u.id)
        if user is None:
            return {"ok": False, "error": "User not found."}
        user.onboarded = True

        # Credit the referrer once, now that this account is fully verified.
        # Blocked only if THIS account is flagged (over the per-IP allowance),
        # so genuine same-network referrals within the allowance still count.
        if user.referred_by and not user.referral_credited:
            referrer = await s.get(User, user.referred_by)
            if referrer is not None and not referrer.is_banned and not user.flagged:
                referrer.balance = q(referrer.balance + credited_amt)
                referrer.total_earned = q(referrer.total_earned + credited_amt)
                referrer.referral_earned = q(referrer.referral_earned + credited_amt)
                credited_to = referrer.id
            # Mark done either way so a self-referral isn't re-checked forever.
            user.referral_credited = True
        await s.commit()

    if credited_to:
        try:
            await bot.send_message(
                credited_to,
                f"🎉 A friend you invited just joined Dollar Bumper — "
                f"<b>{usdt(credited_amt)}</b> added to your balance!",
            )
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


def _clean_url(u: str | None) -> str:
    """Strip stray <> and trailing junk so links pasted as <https://…> still open.
    Fixes tasks already stored with a trailing '>' without needing a re-add."""
    u = (u or "").strip().strip("<>").strip().rstrip("<>.,")
    return u


def _task_url(c: Campaign) -> str:
    if c.link:
        return _clean_url(c.link)
    return f"https://t.me/{c.channel.lstrip('@')}" if c.channel else ""


async def tasks_list(u: WebAppUser) -> dict:
    from app.services.campaigns import active_campaigns_and_done
    from app.services.tasks import display_title

    camps, done_ids = await active_campaigns_and_done(u.id)
    tasks = [
        {
            "id": c.id,
            "title": display_title(c.channel, c.link, c.title),
            "channel": c.channel,
            "reward": _q(c.reward_per_task),
            "description": c.description,
            "kind": c.kind,
            "url": _task_url(c),
            "done": c.id in done_ids,
        }
        for c in camps
    ]
    # Not-done first (so there's always something to do at the top), done last.
    tasks.sort(key=lambda t: t["done"])
    return {"ok": True, "tasks": tasks}


async def task_verify(u: WebAppUser, campaign_id: int, bot: Bot) -> dict:
    async with Session() as s:
        c = await s.get(Campaign, campaign_id)
    if c is None:
        return {"ok": False, "error": "Task not found."}
    # Channel tasks: verify REAL membership before crediting (fail closed).
    # Visit tasks (bot links, private invites, external): honor-based claim.
    if c.kind == "channel" and c.channel:
        joined, reason = await member_status(bot, c.channel, u.id)
        if not joined:
            if ":" in (reason or ""):  # an API error → the bot can't see the channel
                return {"ok": False, "error": (
                    f"⚠️ Can't verify {c.channel} yet — the bot must be an admin "
                    "there. Please try again shortly."
                )}
            return {"ok": False, "error": f"Join {c.channel} first, then tap Claim. ✅"}

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


# ── Games / ads / points (Mini App) ──────────────────────────
async def spin_wheel(u: WebAppUser) -> dict:
    from app.services.rewards import spin
    r = await spin(u.id)
    return {"ok": r.ok, "message": r.message, "reward": r.points,
            "points": r.balance_points, **(r.extra or {})}


async def ad_reward(u: WebAppUser, network: str) -> dict:
    from app.services.rewards import claim_ad
    r = await claim_ad(u.id, network)
    return {"ok": r.ok, "message": r.message, "reward": r.points,
            "points": r.balance_points, **(r.extra or {})}


async def game_finish(u: WebAppUser, score) -> dict:
    from app.services.rewards import game_reward
    r = await game_reward(u.id, score)
    return {"ok": r.ok, "message": r.message, "reward": r.points, "points": r.balance_points}


async def convert_points_action(u: WebAppUser, amount=None) -> dict:
    from app.services.rewards import convert_points
    amt = None
    if amount not in (None, "", "all"):
        try:
            amt = int(amount)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Enter a valid amount."}
    r = await convert_points(u.id, amt)
    return {"ok": r.ok, "message": r.message, "points": r.balance_points, **(r.extra or {})}


# ── Advertiser flow (Mini App) ────────────────────────────────
def _adv_config() -> dict:
    pool = q(settings.advertiser_reward_pool_pct)
    return {
        "min_budget": _q(settings.min_campaign_budget),
        "pay_to": settings.project_wallet_address,
        "network": "BEP20 (BSC)",
        "reward_pool_pct": _q(pool),
        "fee_pct": _q(q(1) - pool),
    }


async def advertise_create(u: WebAppUser, title: str, url: str, reward, budget) -> dict:
    from app.services.campaigns import create_campaign
    from app.services.tasks import classify

    if not settings.project_wallet_address:
        return {"ok": False, "error": "Advertising isn't available right now."}
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "Enter the link you want to promote."}
    try:
        reward_d = q(Decimal(str(reward)))
        budget_d = q(Decimal(str(budget)))
    except (InvalidOperation, ValueError):
        return {"ok": False, "error": "Enter valid numbers for reward and budget."}
    if reward_d <= 0:
        return {"ok": False, "error": "Reward per task must be greater than 0."}
    if budget_d < q(settings.min_campaign_budget):
        return {"ok": False, "error": f"Minimum budget is {_q(settings.min_campaign_budget)} USDT."}
    if budget_d < reward_d:
        return {"ok": False, "error": "Budget must be at least one reward."}

    kind, channel, link, auto_title = classify(url)
    title = (title or "").strip()[:128] or auto_title
    camp = await create_campaign(
        advertiser_id=u.id,
        title=title,
        channel=channel or "",
        reward_per_task=reward_d,
        budget_total=budget_d,
        kind=kind,
        link=link,
    )
    pool = q(settings.advertiser_reward_pool_pct)
    reward_pool = q(budget_d * pool)
    est = int(reward_pool / reward_d) if reward_d > 0 else 0
    cfg = _adv_config()
    return {
        "ok": True,
        "campaign_id": camp.id,
        "amount": _q(budget_d),
        "reward_pool": _q(reward_pool),
        "est_completions": est,
        "verified": kind == "channel",
        **cfg,
    }


async def advertise_verify(u: WebAppUser, campaign_id, tx_hash: str) -> dict:
    from app.services.campaigns import verify_and_activate
    from app.utils.validators import is_valid_tx_hash

    tx = (tx_hash or "").strip()
    if not is_valid_tx_hash(tx):
        return {"ok": False, "error": "That isn't a valid transaction hash (0x + 64 hex)."}
    try:
        cid = int(campaign_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "No campaign in progress."}
    res = await verify_and_activate(cid, tx)
    return {"ok": res.ok, "message": res.message}


async def advertise_list(u: WebAppUser) -> dict:
    from app.services.campaigns import campaigns_by_advertiser
    from app.services.tasks import display_title

    camps = await campaigns_by_advertiser(u.id)
    return {
        "ok": True,
        **_adv_config(),
        "campaigns": [
            {
                "id": c.id,
                "title": display_title(c.channel, c.link, c.title),
                "status": c.status,
                "reward": _q(c.reward_per_task),
                "budget_total": _q(c.budget_total),
                "budget_remaining": _q(c.budget_remaining),
            }
            for c in camps
        ],
    }
