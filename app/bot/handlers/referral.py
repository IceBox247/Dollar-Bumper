"""Invite & Earn panel."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy import func, select

from app.bot import keyboards as kb
from app.bot import ui
from app.bot.handlers.common import referral_link
from app.db.base import Session
from app.db.models import User
from app.services.earning import get_or_create_user

router = Router(name="referral")


@router.message(F.text == kb.BTN_INVITE)
async def invite_panel(message: Message, bot: Bot) -> None:
    u = message.from_user
    user = await get_or_create_user(u.id, u.username, u.first_name, None)
    async with Session() as s:
        invites = await s.scalar(
            select(func.count(User.id)).where(
                User.referred_by == u.id, User.referral_credited.is_(True)
            )
        )
    link = await referral_link(bot, u.id)
    await message.answer(
        ui.referral_panel(user, int(invites or 0), link),
        reply_markup=kb.referral_share(link),
        disable_web_page_preview=True,
    )
