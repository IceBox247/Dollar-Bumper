"""Inline and reply keyboards."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import settings
from app.db.models import Campaign
from app.utils.format import usdt


def app_url() -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/app/" if base else ""


def app_banner_url() -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/app/welcome.jpg" if base else ""


def open_app_inline() -> InlineKeyboardMarkup | None:
    url = app_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Open Dollar Bumper", web_app=WebAppInfo(url=url))
    ]])

# ── Buttons: main navigation (persistent reply keyboard) ──────
BTN_WALLET = "💼 Wallet"
BTN_TASKS = "📋 Earn Tasks"
BTN_INVITE = "👥 Invite & Earn"
BTN_WITHDRAW = "💸 Withdraw"
BTN_ADVERTISE = "📢 Advertise"
BTN_HELP = "ℹ️ Help"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = []
    url = app_url()
    if url:
        rows.append([KeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=url))])
    rows += [
        [KeyboardButton(text=BTN_WALLET), KeyboardButton(text=BTN_TASKS)],
        [KeyboardButton(text=BTN_INVITE), KeyboardButton(text=BTN_WITHDRAW)],
        [KeyboardButton(text=BTN_ADVERTISE), KeyboardButton(text=BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛠️ Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ── Inline keyboards ──────────────────────────────────────────
def join_gate(channels: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📢 Join {c}", url=f"https://t.me/{c.lstrip('@')}")]
        for c in channels
    ]
    rows.append([InlineKeyboardButton(text="✅ I've Joined", callback_data="gate:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Update Wallet", callback_data="wallet:update")
        ]]
    )


def task_card(campaign: Campaign) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📢 Open {campaign.channel}",
                url=f"https://t.me/{campaign.channel.lstrip('@')}",
            )],
            [InlineKeyboardButton(
                text=f"✅ Verify & Claim {usdt(campaign.reward_per_task)}",
                callback_data=f"task:verify:{campaign.id}",
            )],
        ]
    )


def withdraw_options(balance_ok: bool) -> InlineKeyboardMarkup:
    rows = []
    if balance_ok:
        rows.append([InlineKeyboardButton(text="💸 Withdraw All", callback_data="wd:all")])
        rows.append([InlineKeyboardButton(text="✏️ Enter Amount", callback_data="wd:custom")])
    rows.append([InlineKeyboardButton(text="💼 Update Wallet", callback_data="wallet:update")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def advertise_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Feature My Channel", callback_data="adv:new")],
            [InlineKeyboardButton(text="📂 My Campaigns", callback_data="adv:list")],
        ]
    )


def advertise_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm & Get Payment Info", callback_data="adv:confirm")],
            [InlineKeyboardButton(text="✖️ Cancel", callback_data="adv:cancel")],
        ]
    )


def advertise_paid(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔎 I've Paid — Verify Now", callback_data=f"adv:verify:{campaign_id}")
        ]]
    )


def referral_share(link: str) -> InlineKeyboardMarkup:
    share = (
        f"https://t.me/share/url?url={link}"
        f"&text=Earn%20real%20USDT%20with%20Dollar%20Bumper!%20Join%20me%20%F0%9F%91%87"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📤 Share Link", url=share)]]
    )
