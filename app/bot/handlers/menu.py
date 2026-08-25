"""Global menu guard: the persistent reply-keyboard buttons (and /cancel) must
ALWAYS work, even in the middle of a multi-step flow.

Without this, a user part-way through the Advertise wizard who taps 💼 Wallet or
🛠️ Admin gets their tap swallowed by the wizard's free-text step. Registered
first, this clears any in-progress FSM state and then re-raises SkipHandler so
the real button/command handler downstream runs as normal.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import keyboards as kb

router = Router(name="menu_guard")

# Every persistent reply-keyboard label. Tapping any of these aborts a flow.
_MENU_TEXTS = {
    kb.BTN_WALLET, kb.BTN_TASKS, kb.BTN_INVITE,
    kb.BTN_WITHDRAW, kb.BTN_ADVERTISE, kb.BTN_HELP, "🛠️ Admin",
}


@router.message(StateFilter("*"), Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    await message.answer("✖️ Cancelled." if had_state else "Nothing in progress. 👍")


@router.message(StateFilter("*"), F.text.in_(_MENU_TEXTS))
async def menu_break(message: Message, state: FSMContext) -> None:
    # Leave any flow, then let the normal handler for this button take over.
    if await state.get_state() is not None:
        await state.clear()
    raise SkipHandler
