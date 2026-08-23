"""Withdrawal lifecycle: request → (review) → broadcast → confirm → proof post.

Serverless-friendly: broadcasting a payout returns immediately with a tx hash;
a separate `confirm_payouts` pass (run by cron and opportunistically on user
traffic) checks the receipt, then finalizes and posts proof. This keeps every
request well under short function timeouts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.config import settings
from app.constants import WithdrawalStatus
from app.db.base import Session
from app.db.models import User, Withdrawal
from app.utils.format import mask_wallet, q, usdt

log = logging.getLogger(__name__)


@dataclass
class WithdrawResult:
    ok: bool
    message: str
    withdrawal_id: int | None = None
    needs_review: bool = False


async def request_withdrawal(user_id: int, amount: Decimal | None, bot: Bot) -> WithdrawResult:
    """Create a withdrawal. Deducts balance up front; auto-pays below the
    review threshold, otherwise queues for admin review."""
    async with Session() as s:
        user = await s.get(User, user_id)
        if user is None:
            return WithdrawResult(False, "User not found.")
        if user.is_banned:
            return WithdrawResult(False, "Your account is restricted.")
        if not user.wallet_address:
            return WithdrawResult(False, "Set your BEP20 wallet first (Wallet → Update).")

        amount = q(amount if amount is not None else user.balance)
        if amount <= 0:
            return WithdrawResult(False, "Nothing to withdraw yet.")
        if amount < q(settings.min_withdrawal):
            return WithdrawResult(
                False,
                f"Minimum withdrawal is {usdt(settings.min_withdrawal)}. "
                f"Your balance: {usdt(user.balance)}.",
            )
        if amount > q(user.balance):
            return WithdrawResult(False, f"Insufficient balance ({usdt(user.balance)}).")

        # Hold funds immediately so they can't be double-spent.
        user.balance = q(user.balance - amount)

        needs_review = amount >= q(settings.review_threshold)
        wd = Withdrawal(
            user_id=user_id,
            amount=amount,
            wallet_address=user.wallet_address,
            status=(
                WithdrawalStatus.PENDING_REVIEW.value
                if needs_review
                else WithdrawalStatus.QUEUED.value
            ),
        )
        s.add(wd)
        await s.commit()
        await s.refresh(wd)
        wd_id, wallet = wd.id, user.wallet_address

    if needs_review:
        await _notify_admins_review(bot, wd_id, user_id, amount, wallet)
        return WithdrawResult(
            True,
            f"🕵️ Withdrawal of {usdt(amount)} received.\n"
            f"Amounts of {usdt(settings.review_threshold)}+ get a quick manual "
            f"review before payout. You'll be notified once it's sent.",
            wd_id,
            needs_review=True,
        )

    # Below threshold → broadcast right away (confirmation happens async).
    await broadcast_payout(wd_id, bot)
    return WithdrawResult(True, "⚡ Payout sent — confirming on-chain now…", wd_id)


async def broadcast_payout(withdrawal_id: int, bot: Bot) -> None:
    """Sign & broadcast the USDT transfer (no receipt wait). Refunds on error."""
    async with Session() as s:
        wd = await s.get(Withdrawal, withdrawal_id)
        if wd is None or wd.status in (
            WithdrawalStatus.PAID.value,
            WithdrawalStatus.PROCESSING.value,
        ):
            return
        wd.status = WithdrawalStatus.PROCESSING.value
        await s.commit()
        amount, wallet, uid = q(wd.amount), wd.wallet_address, wd.user_id

    from app.services.chain import chain

    try:
        tx_hash = await chain.broadcast_usdt(wallet, amount)
    except Exception as e:  # noqa: BLE001
        log.exception("broadcast failed for withdrawal %s", withdrawal_id)
        async with Session() as s:
            wd = await s.get(Withdrawal, withdrawal_id)
            user = await s.get(User, uid)
            if wd and user:
                wd.status = WithdrawalStatus.FAILED.value
                wd.error = str(e)[:500]
                user.balance = q(user.balance + amount)  # refund the hold
                await s.commit()
        await _safe_dm(bot, uid,
            "⚠️ Your withdrawal couldn't be sent and your balance was refunded. "
            "Please try again shortly.")
        return

    async with Session() as s:
        wd = await s.get(Withdrawal, withdrawal_id)
        if wd:
            wd.tx_hash = tx_hash
            await s.commit()


async def confirm_payouts(bot: Bot, limit: int = 10) -> int:
    """Check broadcast (PROCESSING) payouts, finalize them, post proof.
    Returns the number of withdrawals finalized. Safe to call anytime."""
    async with Session() as s:
        rows = await s.scalars(
            select(Withdrawal)
            .where(
                Withdrawal.status == WithdrawalStatus.PROCESSING.value,
                Withdrawal.tx_hash.is_not(None),
            )
            .order_by(Withdrawal.id.asc())
            .limit(limit)
        )
        pending = list(rows.all())

    if not pending:
        return 0

    from app.services.chain import chain

    finalized = 0
    for wd in pending:
        status = await chain.tx_status(wd.tx_hash)
        if status == "pending":
            continue
        async with Session() as s:
            row = await s.get(Withdrawal, wd.id)
            user = await s.get(User, wd.user_id)
            if row is None or row.status != WithdrawalStatus.PROCESSING.value:
                continue
            if status == "success":
                row.status = WithdrawalStatus.PAID.value
                row.paid_at = datetime.now(timezone.utc)
                await s.commit()
                await _post_proof(bot, q(row.amount), row.wallet_address, row.tx_hash)
                await _safe_dm(bot, row.user_id,
                    f"✅ <b>Paid!</b> {usdt(row.amount)} sent on-chain.\n\n"
                    f"🔗 <a href='{settings.explorer_tx_url}{row.tx_hash}'>View transaction</a>")
            else:  # failed / reverted → refund
                row.status = WithdrawalStatus.FAILED.value
                row.error = "on-chain revert"
                if user:
                    user.balance = q(user.balance + q(row.amount))
                await s.commit()
                await _safe_dm(bot, row.user_id,
                    f"⚠️ Your withdrawal of {usdt(row.amount)} failed on-chain and "
                    "your balance was refunded. Please try again.")
            finalized += 1
    return finalized


async def approve_withdrawal(withdrawal_id: int, admin_id: int, bot: Bot) -> str:
    async with Session() as s:
        wd = await s.get(Withdrawal, withdrawal_id)
        if wd is None:
            return "Not found."
        if wd.status != WithdrawalStatus.PENDING_REVIEW.value:
            return f"Already {wd.status}."
        wd.status = WithdrawalStatus.QUEUED.value
        wd.reviewed_by = admin_id
        await s.commit()
    await broadcast_payout(withdrawal_id, bot)
    return "Approved — paying out (confirming on-chain)."


async def reject_withdrawal(withdrawal_id: int, admin_id: int, bot: Bot) -> str:
    async with Session() as s:
        wd = await s.get(Withdrawal, withdrawal_id)
        if wd is None:
            return "Not found."
        if wd.status != WithdrawalStatus.PENDING_REVIEW.value:
            return f"Already {wd.status}."
        user = await s.get(User, wd.user_id)
        wd.status = WithdrawalStatus.REJECTED.value
        wd.reviewed_by = admin_id
        if user:
            user.balance = q(user.balance + q(wd.amount))  # refund
        uid, amount = wd.user_id, q(wd.amount)
        await s.commit()
    await _safe_dm(bot, uid,
        f"❌ Your withdrawal of {usdt(amount)} was declined after review and "
        "your balance was refunded. Contact support if you believe this is an error.")
    return "Rejected and refunded."


# ── internals ─────────────────────────────────────────────────
async def _safe_dm(bot: Bot, uid: int, text: str) -> None:
    try:
        await bot.send_message(uid, text, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        pass


async def _post_proof(bot: Bot, amount: Decimal, wallet: str, tx_hash: str) -> None:
    if not settings.proof_channel_id:
        return
    text = (
        "🎉 <b>New Withdrawal Paid</b> 🎉\n\n"
        f"💰 Amount : <b>{usdt(amount)}</b> 💎\n"
        f"👛 Wallet : <code>{mask_wallet(wallet)}</code>\n"
        f"⛓️ Network : BEP20 (BSC)"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🧾 Transaction Hash", url=f"{settings.explorer_tx_url}{tx_hash}"
            )
        ]]
    )
    try:
        await bot.send_message(
            settings.proof_channel_id, text, reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("could not post proof to channel: %s", e)


async def _notify_admins_review(bot: Bot, wd_id: int, uid: int, amount: Decimal, wallet: str) -> None:
    text = (
        "🕵️ <b>Withdrawal needs review</b>\n\n"
        f"👤 User : <code>{uid}</code>\n"
        f"💰 Amount : <b>{usdt(amount)}</b>\n"
        f"👛 Wallet : <code>{wallet}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve", callback_data=f"wd_ok:{wd_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"wd_no:{wd_id}"),
        ]]
    )
    for admin_id in settings.admin_ids:
        await _safe_dm_kb(bot, admin_id, text, kb)


async def _safe_dm_kb(bot: Bot, uid: int, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await bot.send_message(uid, text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        pass
