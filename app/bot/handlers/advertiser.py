"""Advertiser flow: create a featured-channel campaign and pay on-chain."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
from app.bot.states import AdvertiseStates
from app.config import settings
from app.constants import CampaignStatus
from app.services.campaigns import (
    campaigns_by_advertiser,
    create_campaign,
    verify_and_activate,
)
from app.utils.format import usdt
from app.utils.validators import is_valid_tx_hash, normalize_channel

router = Router(name="advertiser")


@router.message(F.text == kb.BTN_ADVERTISE)
async def advertise_home(message: Message) -> None:
    await message.answer(ui.advertise_panel(), reply_markup=kb.advertise_start())


@router.callback_query(F.data == "adv:new")
async def adv_new(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdvertiseStates.title)
    await cb.message.answer("📢 <b>Step 1/4</b> — Send a short campaign title (e.g. your project name):")
    await cb.answer()


@router.message(AdvertiseStates.title, F.text, ~F.text.startswith("/"))
async def adv_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip()[:128])
    await state.set_state(AdvertiseStates.channel)
    await message.answer(
        "🔗 <b>Step 2/4</b> — Send your channel's @username or t.me link.\n\n"
        "⚠️ Add this bot as an <b>admin</b> of that channel so we can verify joins."
    )


@router.message(AdvertiseStates.channel, F.text, ~F.text.startswith("/"))
async def adv_channel(message: Message, state: FSMContext) -> None:
    channel = normalize_channel(message.text)
    if not channel:
        await message.answer("❌ That's not a valid channel. Send like <code>@mychannel</code>.")
        return
    await state.update_data(channel=channel)
    await state.set_state(AdvertiseStates.reward)
    await message.answer(
        "💰 <b>Step 3/4</b> — Reward per join (USDT), e.g. <code>0.02</code>:"
    )


@router.message(AdvertiseStates.reward, F.text, ~F.text.startswith("/"))
async def adv_reward(message: Message, state: FSMContext) -> None:
    reward = _parse_amount(message.text)
    if reward is None or reward <= 0:
        await message.answer("❌ Send a positive number, e.g. <code>0.02</code>.")
        return
    await state.update_data(reward=str(reward))
    await state.set_state(AdvertiseStates.budget)
    await message.answer(
        f"💵 <b>Step 4/4</b> — Total budget (USDT), min "
        f"<code>{settings.min_campaign_budget}</code>:"
    )


@router.message(AdvertiseStates.budget, F.text, ~F.text.startswith("/"))
async def adv_budget(message: Message, state: FSMContext) -> None:
    budget = _parse_amount(message.text)
    if budget is None or budget < settings.min_campaign_budget:
        await message.answer(
            f"❌ Minimum budget is {usdt(settings.min_campaign_budget)}. Try again."
        )
        return
    data = await state.get_data()
    reward = Decimal(data["reward"])
    if budget < reward:
        await message.answer("❌ Budget must be at least one reward. Send a larger budget.")
        return
    await state.update_data(budget=str(budget))
    await state.set_state(AdvertiseStates.confirm)
    await message.answer(
        ui.advertise_summary(data["title"], data["channel"], reward, budget),
        reply_markup=kb.advertise_confirm(),
    )


@router.callback_query(AdvertiseStates.confirm, F.data == "adv:confirm")
async def adv_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    campaign = await create_campaign(
        advertiser_id=cb.from_user.id,
        title=data["title"],
        channel=data["channel"],
        reward_per_task=Decimal(data["reward"]),
        budget_total=Decimal(data["budget"]),
    )
    await state.update_data(campaign_id=campaign.id)
    await state.set_state(AdvertiseStates.waiting_tx)
    await cb.message.answer(
        ui.advertise_payment(Decimal(data["budget"])),
        reply_markup=kb.advertise_paid(campaign.id),
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.callback_query(F.data == "adv:cancel")
async def adv_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("✖️ Campaign cancelled.")
    await cb.answer()


@router.message(AdvertiseStates.waiting_tx, F.text, ~F.text.startswith("/"))
async def adv_tx_pasted(message: Message, state: FSMContext) -> None:
    tx = message.text.strip()
    if not is_valid_tx_hash(tx):
        await message.answer("❌ That's not a valid transaction hash (0x + 64 hex chars).")
        return
    data = await state.get_data()
    await _do_verify(message, state, data.get("campaign_id"), tx)


@router.callback_query(F.data.startswith("adv:verify:"))
async def adv_verify_btn(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.answer(
        "🔎 Paste the <b>transaction hash</b> of your payment and I'll verify it on-chain."
    )
    await state.update_data(campaign_id=int(cb.data.split(":")[2]))
    await state.set_state(AdvertiseStates.waiting_tx)


async def _do_verify(message: Message, state: FSMContext, campaign_id: int | None, tx: str) -> None:
    if not campaign_id:
        await message.answer("⚠️ No campaign in progress. Start again from 📢 Advertise.")
        await state.clear()
        return
    await message.answer("⏳ Verifying your payment on-chain…")
    result = await verify_and_activate(campaign_id, tx)
    if result.ok:
        await state.clear()
        await message.answer(ui.advertise_live())
    else:
        await message.answer(f"❌ {result.message}\n\nDouble-check and try again.")


@router.callback_query(F.data == "adv:list")
async def adv_list(cb: CallbackQuery) -> None:
    campaigns = await campaigns_by_advertiser(cb.from_user.id)
    await cb.answer()
    if not campaigns:
        await cb.message.answer("📂 You have no campaigns yet.")
        return
    lines = ["📂 <b>Your campaigns</b>\n"]
    emoji = {
        CampaignStatus.ACTIVE.value: "🟢",
        CampaignStatus.PENDING_PAYMENT.value: "🟡",
        CampaignStatus.COMPLETED.value: "✅",
        CampaignStatus.PAUSED.value: "⏸️",
        CampaignStatus.REJECTED.value: "🔴",
    }
    for c in campaigns:
        lines.append(
            f"{emoji.get(c.status, '•')} <b>{c.title}</b> ({c.channel})\n"
            f"   {c.status} · budget {usdt(c.budget_remaining)}/{usdt(c.budget_total)} left"
        )
    await cb.message.answer("\n".join(lines))


def _parse_amount(text: str) -> Decimal | None:
    raw = (text or "").strip().replace(",", ".").replace("USDT", "").strip()
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
