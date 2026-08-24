"""Async SQLAlchemy engine, session factory, and schema init.

Supports SQLite (local/always-on) and Postgres (serverless). For Postgres it
uses asyncpg with a NullPool so each serverless invocation opens/closes its own
connection cleanly, and honours `sslmode=require` in the URL.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix):]
        if path and path != ":memory:":
            Path(os.path.dirname(path) or ".").mkdir(parents=True, exist_ok=True)


def _build_engine():
    url = settings.database_url
    kwargs: dict = {"echo": False, "future": True}

    if url.startswith("postgres"):
        # Normalize to the asyncpg driver.
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        connect_args: dict = {}
        # asyncpg doesn't understand libpq's ?sslmode=; translate it.
        if "sslmode=require" in url or "ssl=true" in url:
            connect_args["ssl"] = True
        url = re.sub(r"[?&]sslmode=require", "", url)
        url = re.sub(r"[?&]ssl=true", "", url)
        url = re.sub(r"[?&]channel_binding=require", "", url)
        # Disable prepared-statement caching so the pooled (PgBouncer) Neon /
        # Supabase connection string works too, not just the direct one.
        connect_args["statement_cache_size"] = 0
        kwargs["connect_args"] = connect_args
        # Fresh connection per invocation — safe for serverless.
        kwargs["poolclass"] = NullPool
    else:
        _ensure_sqlite_dir(url)

    return create_async_engine(url, **kwargs)


engine = _build_engine()
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_initialized = False


# (table, column, column-type SQL) — added idempotently for live DBs that were
# created before these columns existed (create_all won't alter existing tables).
_MIGRATIONS = [
    ("users", "signup_ip", "VARCHAR(64)"),
    ("users", "flagged", "BOOLEAN DEFAULT FALSE"),
]


async def _run_migrations(conn) -> None:
    dialect = conn.dialect.name
    for table, col, typ in _MIGRATIONS:
        if dialect == "postgresql":
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        else:  # sqlite (local/dev)
            rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
            if col not in {r[1] for r in rows}:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


async def init_db() -> None:
    """Create tables if missing + apply lightweight column migrations. Idempotent."""
    from app.db import models  # noqa: F401  (register models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def ensure_initialized() -> None:
    """Run schema init at most once per process (for serverless cold starts)."""
    global _initialized
    if _initialized:
        return
    await init_db()
    _initialized = True
