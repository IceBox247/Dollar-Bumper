"""Withdraw flow."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
from app.bot.states import WithdrawStates
from app.config import settings
from app.services.earning import get_or_create_user
from app.services.payouts import request_withdrawal

router = Router(name="withdraw")


@router.message(F.text == kb.BTN_WITHDRAW)
async def withdraw_panel(message: Message) -> None:
    u = message.from_user
    user = await get_or_create_user(u.id, u.username, u.first_name, None)
    balance_ok = user.balance >= settings.min_withdrawal and bool(user.wallet_address)
    await message.answer(
        ui.withdraw_panel(user), reply_markup=kb.withdraw_options(balance_ok)
    )


@router.callback_query(F.data == "wd:all")
async def withdraw_all(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    result = await request_withdrawal(cb.from_user.id, None, bot)
    await cb.answer()
    await cb.message.answer(result.message)


@router.callback_query(F.data == "wd:custom")
async def withdraw_custom(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WithdrawStates.waiting_amount)
    await cb.message.answer(
        f"✏️ Enter the amount to withdraw (min {settings.min_withdrawal} USDT):"
    )
    await cb.answer()


@router.message(WithdrawStates.waiting_amount, F.text)
async def withdraw_amount(message: Message, bot: Bot, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".").replace("USDT", "").strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        await message.answer("❌ Please send a number, e.g. <code>2.5</code>.")
        return
    await state.clear()
    result = await request_withdrawal(message.from_user.id, amount, bot)
    await message.answer(result.message)
