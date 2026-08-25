"""Admin commands: stats, pending reviews, wallet funding, approvals, bans."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

from app.config import settings
from app.constants import CampaignStatus, WithdrawalStatus
from app.db.base import Session
from app.db.models import Campaign, User, Withdrawal
from app.services.payouts import approve_withdrawal, reject_withdrawal
from app.utils.format import mask_wallet, q, usdt

router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return settings.is_admin(user_id)


def _uid(args: str | None) -> int | None:
    """Extract a user id from args, tolerating <brackets>, spaces, etc."""
    if not args:
        return None
    m = re.search(r"\d{3,}", args)
    return int(m.group()) if m else None


@router.message(Command("stats"))
async def stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with Session() as s:
        users = await s.scalar(select(func.count(User.id)))
        active = await s.scalar(
            select(func.count(Campaign.id)).where(
                Campaign.status == CampaignStatus.ACTIVE.value
            )
        )
        paid = await s.scalar(
            select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
                Withdrawal.status == WithdrawalStatus.PAID.value
            )
        )
        pending = await s.scalar(
            select(func.count(Withdrawal.id)).where(
                Withdrawal.status == WithdrawalStatus.PENDING_REVIEW.value
            )
        )
    text = (
        "🛠️ <b>Admin — Stats</b>\n\n"
        f"👥 Users : <b>{users or 0}</b>\n"
        f"🟢 Active campaigns : <b>{active or 0}</b>\n"
        f"💸 Total paid out : <b>{usdt(paid or 0)}</b>\n"
        f"🕵️ Pending reviews : <b>{pending or 0}</b>\n\n"
        "Commands: /pending · /fund · /ban &lt;id&gt; · /unban &lt;id&gt;"
    )
    await message.answer(text)


@router.message(Command("fund"))
async def fund(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    from app.services.chain import chain

    try:
        usdt_bal = await chain.payout_balance()
        bnb_bal = await chain.gas_balance()
    except Exception as e:  # noqa: BLE001
        await message.answer(f"⚠️ Could not read payout wallet: {e}")
        return
    warn = "\n\n⚠️ <b>Low BNB for gas — top up!</b>" if bnb_bal < 0.005 else ""
    await message.answer(
        "⛽ <b>Payout wallet</b>\n\n"
        f"Address : <code>{settings.payout_wallet_address}</code>\n"
        f"💵 USDT : <b>{usdt(usdt_bal)}</b>\n"
        f"🔸 BNB (gas) : <b>{bnb_bal:.5f}</b>{warn}"
    )


@router.message(Command("pending"))
async def pending(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with Session() as s:
        rows = await s.scalars(
            select(Withdrawal)
            .where(Withdrawal.status == WithdrawalStatus.PENDING_REVIEW.value)
            .order_by(Withdrawal.id.asc())
            .limit(20)
        )
        items = list(rows.all())
    if not items:
        await message.answer("✅ No withdrawals awaiting review.")
        return
    for wd in items:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve", callback_data=f"wd_ok:{wd.id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"wd_no:{wd.id}"),
            ]]
        )
        await message.answer(
            f"🕵️ #{wd.id} · user <code>{wd.user_id}</code>\n"
            f"💰 {usdt(wd.amount)} → <code>{mask_wallet(wd.wallet_address)}</code>",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("wd_ok:"))
async def cb_approve(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not authorized.", show_alert=True)
        return
    wd_id = int(cb.data.split(":")[1])
    msg = await approve_withdrawal(wd_id, cb.from_user.id, bot)
    await cb.answer(msg, show_alert=True)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("wd_no:"))
async def cb_reject(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Not authorized.", show_alert=True)
        return
    wd_id = int(cb.data.split(":")[1])
    msg = await reject_withdrawal(wd_id, cb.from_user.id, bot)
    await cb.answer(msg, show_alert=True)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("ban"))
async def ban(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _set_ban(message, command, True)


@router.message(Command("unban"))
async def unban(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _set_ban(message, command, False)


@router.message(Command("credit"))
async def credit(message: Message, command: CommandObject) -> None:
    """Admin: adjust a user's balance. Usage: /credit <user_id> <amount>
    Use a negative amount to deduct."""
    if not _is_admin(message.from_user.id):
        return
    parts = (command.args or "").split()
    uid = _uid(parts[0]) if parts else None
    if uid is None or len(parts) < 2:
        await message.answer("Usage: <code>/credit 123456789 0.06</code>")
        return
    try:
        amount = Decimal(parts[1])
    except (ValueError, InvalidOperation):
        await message.answer("❌ Bad amount. Example: <code>/credit 123456789 0.06</code>")
        return
    async with Session() as s:
        user = await s.get(User, uid)
        if user is None:
            await message.answer("User not found (they must /start the bot first).")
            return
        user.balance = q(user.balance + amount)
        new_balance = user.balance
        await s.commit()
    await message.answer(
        f"✅ Adjusted <code>{uid}</code> by {usdt(amount)}.\nNew balance: <b>{usdt(new_balance)}</b>"
    )
    try:
        await message.bot.send_message(
            uid, f"💰 Your balance was updated by an admin: {usdt(amount)}."
        )
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("wd"))
async def wd_status(message: Message, command: CommandObject) -> None:
    """Inspect withdrawals. /wd  (last 10)  or  /wd <withdrawal_id>"""
    if not _is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    async with Session() as s:
        if arg.isdigit():
            w = await s.get(Withdrawal, int(arg))
            rows = [w] if w else []
        else:
            rows = list((await s.scalars(
                select(Withdrawal).order_by(Withdrawal.id.desc()).limit(10)
            )).all())
    if not rows:
        await message.answer("No withdrawals found.")
        return
    lines = ["💸 <b>Withdrawals</b> (newest first):"]
    for w in rows:
        tx = f"\n   🔗 <code>{w.tx_hash}</code>" if w.tx_hash else ""
        err = f"\n   ⚠️ {w.error[:140]}" if w.error else ""
        lines.append(
            f"#{w.id} · user <code>{w.user_id}</code> · {usdt(w.amount)} · "
            f"<b>{w.status}</b>{tx}{err}"
        )
    await message.answer("\n".join(lines), disable_web_page_preview=True)


@router.message(Command("whois"))
async def whois(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    uid = _uid(command.args)
    if uid is None:
        await message.answer("Usage: /whois 123456789")
        return
    async with Session() as s:
        u = await s.get(User, uid)
    if u is None:
        await message.answer("User not found.")
        return
    await message.answer(
        f"👤 <code>{uid}</code>\n"
        f"Name: {u.first_name} (@{u.username})\n"
        f"Balance: {usdt(u.balance)} · Earned: {usdt(u.total_earned)}\n"
        f"Wallet: <code>{u.wallet_address or '—'}</code>\n"
        f"IP: <code>{u.signup_ip or '—'}</code>\n"
        f"Onboarded: {u.onboarded} · Flagged: {u.flagged} · Banned: {u.is_banned}"
    )


def _parse_reward_line(line: str, prefixes: tuple[str, ...]) -> Decimal | None:
    """Parse 'reward=0.001' / 'reward 0.001' / 'reward: 0.001' (case-insensitive)."""
    low = line.lower().strip()
    for p in prefixes:
        if low.startswith(p):
            rest = line[len(p):].lstrip(" =:").replace(",", ".").replace("USDT", "").strip()
            try:
                return Decimal(rest)
            except (InvalidOperation, ValueError):
                return None
    return None


def _is_telegram_link(url: str) -> bool:
    u = url.strip().lower()
    if re.fullmatch(r"@?[a-z0-9_]{4,32}", u):
        return True
    return bool(re.search(r"(?:https?://)?(?:t|telegram)\.me/", u))


@router.message(Command("addtasks"))
async def addtasks(message: Message, command: CommandObject) -> None:
    """Bulk-add earn tasks. Paste one link per line after the command.

    Optional lines:
      reward=0.001         base reward (Telegram links)
      nontg_reward=0.0015  reward for non-Telegram links (WhatsApp, sites, …)
    Angle brackets around links (<https://…>) are tolerated.
    """
    if not _is_admin(message.from_user.id):
        return
    from app.services.membership import bot_can_verify
    from app.services.tasks import classify, create_task

    text = command.args or ""
    reward = Decimal("0.001")
    nontg_reward: Decimal | None = None
    urls: list[str] = []
    for line in text.splitlines():
        line = line.strip().strip("<>").strip()
        if not line:
            continue
        r = _parse_reward_line(line, ("reward",))
        if r is not None and not re.search(r"https?://|t\.me/", line.lower()):
            reward = r
            continue
        nr = _parse_reward_line(line, ("nontg_reward", "non_tg_reward", "visit_reward"))
        if nr is not None:
            nontg_reward = nr
            continue
        m = re.search(r"https?://[^\s<>]+", line)
        if m:
            urls.append(m.group().rstrip("<>.,"))
        elif re.fullmatch(r"@[A-Za-z0-9_]{4,32}", line):
            urls.append(line)
    if not urls:
        await message.answer(
            "Paste task links (one per line) after the command.\n\n"
            "<code>/addtasks\nreward=0.001\nnontg_reward=0.0015\n"
            "https://t.me/YourChannel\nhttps://whatsapp.com/channel/xxxx</code>\n\n"
            "Telegram links use <b>reward</b>; anything else uses <b>nontg_reward</b>."
        )
        return
    if nontg_reward is None:
        nontg_reward = reward

    created = tg_n = other_n = verify_n = 0
    needs_admin: list[str] = []
    for url in urls:
        kind, ch, ln, title = classify(url)
        # Keep Telegram channels VERIFIABLE (kind stays "channel") so joins are
        # checked before crediting. Just flag channels the bot can't yet verify.
        if kind == "channel" and ch:
            verify_n += 1
            if not await bot_can_verify(message.bot, ch):
                needs_admin.append(ch)
        is_tg = _is_telegram_link(url)
        r = reward if is_tg else nontg_reward
        await create_task(kind, title, ch, ln, r, message.from_user.id)
        created += 1
        tg_n += int(is_tg)
        other_n += int(not is_tg)
    msg = (
        f"✅ Added <b>{created}</b> task(s).\n"
        f"• {tg_n} Telegram @ {usdt(reward)}\n"
        f"• {other_n} other @ {usdt(nontg_reward)}\n"
        f"• 🔒 {verify_n} require a verified join before payout\n"
    )
    if needs_admin:
        chans = ", ".join(dict.fromkeys(needs_admin))
        msg += (
            "\n⚠️ <b>Add this bot as an ADMIN</b> in these channels or joins "
            f"can't be verified and users can't claim:\n{chans}"
        )
    msg += "\n\nUse /tasks to review."
    await message.answer(msg)


@router.message(Command("reverifytasks"))
async def reverifytasks(message: Message, command: CommandObject) -> None:
    """Upgrade existing public-channel tasks to verified joins (bot must be admin).
    Keeps all tasks and completions — no re-add needed."""
    if not _is_admin(message.from_user.id):
        return
    from app.services.tasks import reverify_channel_tasks

    await message.answer("🔎 Checking channels and upgrading tasks…")
    upgraded, cant = await reverify_channel_tasks(message.bot)
    msg = (
        f"🔒 Upgraded <b>{upgraded}</b> task(s) to <b>verified</b> joins — users "
        "must now actually join before they're paid."
    )
    if cant:
        chans = ", ".join(dict.fromkeys(cant))
        msg += (
            "\n\n⚠️ Bot is still <b>not admin</b> in these, so they stay "
            f"open-and-claim until you add it:\n{chans}"
        )
    if not upgraded and not cant:
        msg = "No public Telegram-channel tasks to upgrade (bots, private invites and websites can't be verified)."
    await message.answer(msg)


@router.message(Command("cleartasks"))
async def cleartasks(message: Message, command: CommandObject) -> None:
    """Delete ALL tasks. Requires confirmation: /cleartasks yes"""
    if not _is_admin(message.from_user.id):
        return
    from app.services.tasks import clear_all_tasks

    if (command.args or "").strip().lower() not in {"yes", "confirm", "y"}:
        await message.answer(
            "⚠️ This deletes <b>every</b> task. To confirm, send:\n"
            "<code>/cleartasks yes</code>"
        )
        return
    n = await clear_all_tasks()
    await message.answer(f"🧹 Cleared <b>{n}</b> task(s). Add fresh ones with /addtasks.")


@router.message(Command("tasks"))
async def list_tasks_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    from app.services.tasks import all_tasks, display_title

    ts = await all_tasks()
    if not ts:
        await message.answer("No tasks yet. Add some with /addtasks.")
        return
    lines = ["📋 <b>Tasks</b> (newest first):"]
    for c in ts[:60]:
        tag = "✅verify" if c.kind == "channel" else "🔗visit"
        name = display_title(c.channel, c.link, c.title)
        lines.append(f"#{c.id} {tag} · {name} · {usdt(c.reward_per_task)} · {c.status}")
    await message.answer("\n".join(lines))


@router.message(Command("deltask"))
async def deltask(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    m = re.search(r"\d+", command.args or "")
    if not m:
        await message.answer("Usage: /deltask 12")
        return
    from app.services.tasks import delete_task

    ok = await delete_task(int(m.group()))
    await message.answer("🗑️ Task deleted." if ok else "Task not found.")


@router.message(Command("checkjoin"))
async def checkjoin(message: Message, command: CommandObject) -> None:
    """Diagnose channel-membership checks. /checkjoin [user_id]"""
    if not _is_admin(message.from_user.id):
        return
    uid = _uid(command.args) or message.from_user.id
    if not settings.required_channels:
        await message.answer("No REQUIRED_CHANNELS configured.")
        return
    lines = [f"🔎 Channel check for <code>{uid}</code>:"]
    for ch in settings.required_channels:
        try:
            m = await message.bot.get_chat_member(ch, uid)
            lines.append(f"• {ch} → <b>{m.status}</b>")
        except Exception as e:  # noqa: BLE001
            lines.append(f"• {ch} → ⚠️ {type(e).__name__}: {str(e)[:80]}")
    lines.append("\nIf you see an error, the bot isn't admin of that channel "
                 "(or the @username is wrong).")
    await message.answer("\n".join(lines))


@router.message(Command("checkadmin"))
async def checkadmin(message: Message, command: CommandObject) -> None:
    """Is the bot an admin of a channel? /checkadmin @channel"""
    if not _is_admin(message.from_user.id):
        return
    m = re.search(r"@?[A-Za-z0-9_]{4,32}", command.args or "")
    if not m:
        await message.answer("Usage: <code>/checkadmin @channel</code>")
        return
    ch = "@" + m.group().lstrip("@")
    try:
        bot_id = (await message.bot.me()).id
        cm = await message.bot.get_chat_member(ch, bot_id)
        ok = cm.status in {"administrator", "creator"}
        await message.answer(
            f"{'✅' if ok else '❌'} Bot status in {ch}: <b>{cm.status}</b>\n\n"
            + ("The bot can verify joins here. Run /reverifytasks to enable it."
               if ok else
               "The bot must be an <b>admin</b> here to verify joins. "
               "Add it as admin (read members is enough), then /reverifytasks.")
        )
    except Exception as e:  # noqa: BLE001
        await message.answer(
            f"❌ {ch} → {type(e).__name__}: {str(e)[:100]}\n\n"
            "Usually means the bot isn't in the channel, or the @username is wrong. "
            "For a private channel, the bot must be added as an admin."
        )


@router.message(Command("refs"))
async def refs(message: Message, command: CommandObject) -> None:
    """List a user's referrals and why each did/didn't pay. /refs [user_id]"""
    if not _is_admin(message.from_user.id):
        return
    uid = _uid(command.args) or message.from_user.id
    async with Session() as s:
        rows = list((await s.scalars(
            select(User).where(User.referred_by == uid).order_by(User.created_at.desc())
        )).all())
    if not rows:
        await message.answer(f"No referrals found for <code>{uid}</code>.")
        return
    paid = 0
    lines = [f"👥 <b>Referrals of</b> <code>{uid}</code> — {len(rows)} total:"]
    for r in rows[:40]:
        name = r.first_name or (("@" + r.username) if r.username else str(r.id))
        if not r.onboarded:
            status = "⏳ hasn't finished onboarding (join channels)"
        elif r.flagged:
            status = "⚠️ flagged (same device/IP) — not paid"
        elif r.referral_credited:
            status = "✅ paid"
            paid += 1
        else:
            status = "… pending"
        lines.append(f"• {name} — {status}")
    lines.append(f"\n💰 Paid referrals: <b>{paid}</b>")
    if len(rows) > 40:
        lines.append(f"(showing 40 of {len(rows)})")
    await message.answer("\n".join(lines))


@router.message(Command("unflag"))
async def unflag(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    uid = _uid(command.args)
    if uid is None:
        await message.answer("Usage: /unflag 123456789")
        return
    async with Session() as s:
        u = await s.get(User, uid)
        if u is None:
            await message.answer("User not found.")
            return
        u.flagged = False
        await s.commit()
    await message.answer(f"✅ Cleared multi-account flag for <code>{uid}</code>.")


@router.message(Command("reset_onboarding"))
async def reset_onboarding(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    uid = _uid(command.args)
    if uid is None:
        await message.answer("Usage: /reset_onboarding 123456789")
        return
    async with Session() as s:
        u = await s.get(User, uid)
        if u is None:
            await message.answer("User not found.")
            return
        u.onboarded = False
        u.flagged = False
        u.signup_ip = None
        await s.commit()
    await message.answer(
        f"🔄 Reset onboarding for <code>{uid}</code> (onboarded/flagged/IP cleared). "
        "Reopen the app to run it again."
    )


async def _set_ban(message: Message, command: CommandObject, banned: bool) -> None:
    uid = _uid(command.args)
    if uid is None:
        await message.answer("Usage: /ban 123456789")
        return
    async with Session() as s:
        user = await s.get(User, uid)
        if user is None:
            await message.answer("User not found.")
            return
        user.is_banned = banned
        await s.commit()
    await message.answer(f"{'🚫 Banned' if banned else '✅ Unbanned'} <code>{uid}</code>.")
