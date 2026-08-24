"""One persistent event loop per serverless process.

Vercel's Python functions handle one request at a time per warm instance, but
each request used to call ``asyncio.run`` — which creates AND destroys a fresh
event loop every time. That threw away pooled DB connections and left the
module-cached aiogram Bot holding an aiohttp session bound to a dead loop.

By reusing a single loop for the life of the process, warm invocations reuse
the DB connection pool and the Telegram session, which is the difference
between a snappy Mini App and one that stalls on every tap.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, TypeVar

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro: Awaitable[_T]) -> _T:
    """Run ``coro`` to completion on this process's persistent loop."""
    return _get_loop().run_until_complete(coro)
