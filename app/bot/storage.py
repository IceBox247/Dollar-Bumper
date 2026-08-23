"""A SQLAlchemy-backed aiogram FSM storage.

Persists state/data in the app DB so multi-step flows work across serverless
invocations (where in-memory storage would be lost between requests).
"""
from __future__ import annotations

from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from app.db.base import Session
from app.db.models import FSMRecord


def _key(key: StorageKey) -> str:
    return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id or 0}:{key.destiny}"


def _state_str(state: Any) -> str | None:
    if state is None:
        return None
    if isinstance(state, State):
        return state.state
    return str(state)


class SQLAlchemyStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: Any = None) -> None:
        k, value = _key(key), _state_str(state)
        async with Session() as s:
            rec = await s.get(FSMRecord, k)
            if rec is None:
                rec = FSMRecord(key=k, state=value, data={})
                s.add(rec)
            else:
                rec.state = value
            await s.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with Session() as s:
            rec = await s.get(FSMRecord, k := _key(key))  # noqa: F841
            return rec.state if rec else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        k = _key(key)
        async with Session() as s:
            rec = await s.get(FSMRecord, k)
            if rec is None:
                rec = FSMRecord(key=k, state=None, data=dict(data))
                s.add(rec)
            else:
                rec.data = dict(data)
            await s.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with Session() as s:
            rec = await s.get(FSMRecord, _key(key))
            return dict(rec.data) if rec and rec.data else {}

    async def close(self) -> None:  # nothing to release; engine is shared
        return None
