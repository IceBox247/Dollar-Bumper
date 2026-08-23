"""FSM states for multi-step flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class WalletStates(StatesGroup):
    waiting_address = State()


class WithdrawStates(StatesGroup):
    waiting_amount = State()


class AdvertiseStates(StatesGroup):
    title = State()
    channel = State()
    reward = State()
    budget = State()
    confirm = State()
    waiting_tx = State()
