"""Earn Tasks: list featured channels, verify join, credit reward."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
from app.db.base import Session
from app.db.models import Campaign, User
from app.services.campaigns import active_campaigns_for
from app.services.earning import complete_task, get_or_create_user
from app.services.membership import member_status
from app.utils.format import usdt

router = Router(name="tasks")

_MAX_CARDS = 8


@router.message(F.text == kb.BTN_TASKS)
async def list_tasks(message: Message) -> None:
    u = message.from_user
    await get_or_create_user(u.id, u.username, u.first_name, None)
    campaigns = await active_campaigns_for(u.id)
    if not campaigns:
        await message.answer(ui.no_tasks())
        return
    await message.answer(ui.task_intro(len(campaigns)))
    for c in campaigns[:_MAX_CARDS]:
        await message.answer(ui.task_card_text(c), reply_markup=kb.task_card(c))


@router.callback_query(F.data.startswith("task:verify:"))
async def verify_task(cb: CallbackQuery, bot: Bot) -> None:
    campaign_id = int(cb.data.split(":")[2])
    async with Session() as s:
        campaign = await s.get(Campaign, campaign_id)
    if campaign is None:
        await cb.answer("Task not found.", show_alert=True)
        return

    # Channel tasks require a REAL membership check before crediting (fail closed).
    # Visit tasks (bot links, private invites, external) are open-and-claim.
    if campaign.kind == "channel" and campaign.channel:
        joined, reason = await member_status(bot, campaign.channel, cb.from_user.id)
        if not joined:
            if ":" in (reason or ""):  # API error → bot isn't admin / can't see it
                await cb.answer(
                    f"Can't verify {campaign.channel} yet — the bot must be admin there.",
                    show_alert=True,
                )
                return
            await cb.answer("You haven't joined yet — join, then verify.", show_alert=True)
            await cb.message.answer(ui.task_not_joined(campaign.channel))
            return

    result = await complete_task(cb.from_user.id, campaign_id)
    if not result.ok:
        await cb.answer(result.message, show_alert=True)
        return

    async with Session() as s:
        user = await s.get(User, cb.from_user.id)
        balance = user.balance if user else result.reward

    await cb.answer("Reward credited! ✅")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(ui.task_rewarded(result.reward, balance))

    # Notify the referrer their bonus landed.
    if result.referral_bonus_to:
        try:
            await bot.send_message(
                result.referral_bonus_to,
                f"🎉 A friend you invited just completed a task — "
                f"<b>{usdt(result.referral_bonus_amount)}</b> added to your balance!",
            )
        except Exception:  # noqa: BLE001
            pass
