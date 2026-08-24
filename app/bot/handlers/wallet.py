"""Wallet view + set/update address."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
from app.bot.states import WalletStates
from app.db.base import Session
from app.db.models import User
from app.services.earning import get_or_create_user
from app.utils.validators import is_valid_evm_address, to_checksum

router = Router(name="wallet")


@router.message(F.text == kb.BTN_WALLET)
async def show_wallet(message: Message) -> None:
    u = message.from_user
    user = await get_or_create_user(u.id, u.username, u.first_name, None)
    await message.answer(ui.wallet_view(user), reply_markup=kb.wallet_actions())


@router.callback_query(F.data == "wallet:update")
async def ask_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_address)
    await cb.message.answer(ui.need_wallet())
    await cb.answer()


@router.message(WalletStates.waiting_address, F.text, ~F.text.startswith("/"))
async def save_wallet(message: Message, state: FSMContext) -> None:
    address = (message.text or "").strip()
    if not is_valid_evm_address(address):
        await message.answer(ui.invalid_wallet())
        return
    checksummed = to_checksum(address)
    async with Session() as s:
        user = await s.get(User, message.from_user.id)
        if user is None:
            user = User(id=message.from_user.id, username=message.from_user.username,
                        first_name=message.from_user.first_name)
            s.add(user)
        user.wallet_address = checksummed
        await s.commit()
    await state.clear()
    await message.answer(ui.wallet_saved(checksummed))
