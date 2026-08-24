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
