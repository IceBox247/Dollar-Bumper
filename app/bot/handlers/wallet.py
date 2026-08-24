"""Wallet view + set/update address."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
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
async def ask_wallet(cb: CallbackQuery) -> None:
    # No FSM state needed — a valid 0x… address is accepted any time below.
    await cb.message.answer(ui.need_wallet())
    await cb.answer()


# Accept a valid BEP20 address ANY time — no FSM state, so it never shadows the
# menu buttons (which was breaking navigation during onboarding).
@router.message(F.text.regexp(r"(?i)^\s*0x[0-9a-f]{40}\s*$"))
async def save_wallet(message: Message) -> None:
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
    await message.answer(ui.wallet_saved(checksummed))
