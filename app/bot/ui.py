"""Polished message text builders (HTML parse mode)."""
from __future__ import annotations

from decimal import Decimal

from app.config import settings
from app.db.models import Campaign, User
from app.utils.format import usdt

BRAND = "💵 <b>Dollar Bumper</b>"


def welcome(first_name: str | None) -> str:
    name = first_name or "there"
    return (
        f"{BRAND}\n\n"
        f"👋 Welcome, <b>{name}</b>!\n\n"
        "🚀 A real advertising marketplace — <b>projects pay to be featured</b>, "
        "and <b>you get paid in real USDT</b> for completing quick tasks and "
        "inviting friends.\n\n"
        f"🎁 <b>{usdt(settings.referral_reward)}</b> per valid referral\n"
        f"💸 <b>{usdt(settings.min_withdrawal)}</b> minimum withdrawal — "
        "paid on-chain, <b>no conditions</b>\n\n"
        "Use the menu below to get started 👇"
    )


def need_wallet() -> str:
    return (
        "📝 <b>One quick step</b>\n\n"
        "Send your <b>USDT (BEP20 / BSC)</b> wallet address so we know where to "
        "pay you.\n\n"
        "Paste it below as a message (starts with <code>0x…</code>)."
    )


def wallet_view(user: User) -> str:
    wallet = user.wallet_address or "— not set —"
    return (
        "💼 <b>Your Wallet</b>\n\n"
        f"💰 Balance : <b>{usdt(user.balance)}</b>\n"
        f"🏆 Total earned : {usdt(user.total_earned)}\n"
        f"👥 From referrals : {usdt(user.referral_earned)}\n\n"
        f"🆔 Account ID : <code>{user.id}</code>\n"
        f"⛓️ USDT (BEP20) : <code>{wallet}</code>"
    )


def wallet_saved(address: str) -> str:
    return (
        "🎉 <b>Wallet saved!</b>\n\n"
        f"<code>{address}</code>\n\n"
        "You're all set. Head to <b>📋 Earn Tasks</b> to start earning."
    )


def invalid_wallet() -> str:
    return (
        "❌ That doesn't look like a valid BEP20 address.\n"
        "It should start with <code>0x</code> and be 42 characters long. Try again."
    )


def no_tasks() -> str:
    return (
        "📭 <b>No tasks right now</b>\n\n"
        "All available tasks are claimed or you've completed them. "
        "New featured channels are added regularly — check back soon, or invite "
        "friends to earn in the meantime! 👥"
    )


def task_intro(count: int) -> str:
    return (
        "📋 <b>Earn Tasks</b>\n\n"
        f"There {'is' if count == 1 else 'are'} <b>{count}</b> task"
        f"{'' if count == 1 else 's'} available. "
        "Join the channel, then tap <b>Verify &amp; Claim</b> to get paid.\n"
        "One reward per task, per account."
    )


def task_card_text(c: Campaign) -> str:
    from app.services.tasks import display_title

    title = display_title(c.channel, c.link, c.title)
    desc = f"\n💬 {c.description}" if c.description else ""
    action = "Join & verify" if c.kind == "channel" else "Open & claim"
    return (
        f"📢 <b>{title}</b>{desc}\n\n"
        f"🎯 {action}\n"
        f"💰 Reward : <b>{usdt(c.reward_per_task)}</b>"
    )


def task_not_joined(channel: str) -> str:
    return (
        f"🤔 We couldn't confirm you joined <b>{channel}</b> yet.\n\n"
        "Make sure you actually joined (and didn't leave), then tap "
        "<b>Verify &amp; Claim</b> again."
    )


def task_rewarded(reward: Decimal, new_balance: Decimal) -> str:
    return (
        f"✅ <b>Verified!</b> {usdt(reward)} added to your balance.\n\n"
        f"💰 New balance : <b>{usdt(new_balance)}</b>"
    )


def referral_panel(user: User, invites: int, link: str) -> str:
    return (
        "👥 <b>Invite &amp; Earn</b>\n\n"
        f"🚀 Invite friends and stack up <b>real USDT</b>!\n"
        f"🎁 You receive <b>{usdt(settings.referral_reward)}</b> for every friend "
        "who joins and completes their first task.\n\n"
        f"🔗 <b>Your referral link:</b>\n{link}\n\n"
        f"👥 Total valid invites : <b>{invites}</b>\n"
        f"💰 Referral earnings : <b>{usdt(user.referral_earned)}</b>"
    )


def withdraw_panel(user: User) -> str:
    return (
        "💸 <b>Withdraw</b>\n\n"
        f"💰 Balance : <b>{usdt(user.balance)}</b>\n"
        f"📉 Minimum : {usdt(settings.min_withdrawal)}\n"
        f"⛓️ Network : BEP20 (BSC)\n\n"
        f"Withdrawals under {usdt(settings.review_threshold)} are paid instantly. "
        "Larger ones get a quick manual review first."
    )


def advertise_panel() -> str:
    return (
        "📢 <b>Advertise on Dollar Bumper</b>\n\n"
        "Drive real, engaged users to your <b>Telegram, WhatsApp, YouTube, X or "
        "website</b>. You set the reward per action and your total budget — we "
        "handle delivery.\n\n"
        f"💵 Minimum budget : <b>{usdt(settings.min_campaign_budget)}</b>\n"
        "⛓️ Pay in USDT (BEP20), verified automatically on-chain.\n\n"
        "Ready to feature your link?"
    )


def advertise_summary(title: str, channel: str, reward: Decimal, budget: Decimal) -> str:
    joins = int(budget / reward) if reward > 0 else 0
    return (
        "🧾 <b>Review your campaign</b>\n\n"
        f"📢 Title : <b>{title}</b>\n"
        f"🔗 Target : {channel}\n"
        f"💰 Reward per action : <b>{usdt(reward)}</b>\n"
        f"💵 Total budget : <b>{usdt(budget)}</b>\n"
        f"👥 Est. joins delivered : <b>~{joins}</b>\n\n"
        "Confirm to get the payment address."
    )


def advertise_payment(budget: Decimal) -> str:
    return (
        "💳 <b>Fund your campaign</b>\n\n"
        f"Send exactly <b>{usdt(budget)}</b> in <b>USDT (BEP20 / BSC)</b> to:\n\n"
        f"<code>{settings.project_wallet_address}</code>\n\n"
        "Then paste the <b>transaction hash</b> here (or tap the button after "
        "paying) and we'll verify it on-chain and take your campaign live. ⛓️"
    )


def advertise_live() -> str:
    return (
        "🎉 <b>Payment verified — your campaign is LIVE!</b>\n\n"
        "Your channel is now featured in <b>📋 Earn Tasks</b>. "
        "Track progress under <b>My Campaigns</b>."
    )


def help_text() -> str:
    return (
        "ℹ️ <b>How Dollar Bumper works</b>\n\n"
        "<b>Earn</b>\n"
        "• 📋 Complete tasks (join featured channels) → get paid per task\n"
        f"• 👥 Invite friends → {usdt(settings.referral_reward)} each when they complete a task\n"
        f"• 💸 Withdraw from {usdt(settings.min_withdrawal)}, on-chain, no conditions\n\n"
        "<b>Advertise</b>\n"
        "• 📢 Feature your channel, set reward + budget, pay in USDT\n"
        "• Real users, verified joins, transparent delivery\n\n"
        "All withdrawals are posted publicly with a live BscScan link. 🔗"
    )
