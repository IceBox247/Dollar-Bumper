"""Async SQLAlchemy engine, session factory, and schema init.

Supports SQLite (local/always-on) and Postgres (serverless). For Postgres it
uses asyncpg with a NullPool so each serverless invocation opens/closes its own
connection cleanly, and honours `sslmode=require` in the URL.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

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
        # Keep a small warm pool so warm serverless invocations reuse the SSL
        # connection instead of re-handshaking every request. Safe because this
        # process pins one persistent event loop (see app/_aio.py); pre-ping +
        # recycle guard against a connection dropped while the container idled.
        kwargs["pool_size"] = 1
        kwargs["max_overflow"] = 2
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 280
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
    ("users", "onboarded", "BOOLEAN DEFAULT FALSE"),
    ("campaigns", "kind", "VARCHAR(16) DEFAULT 'channel'"),
    ("campaigns", "link", "TEXT"),
    ("users", "points", "BIGINT DEFAULT 0"),
    ("users", "last_spin_at", "TIMESTAMPTZ"),
    ("users", "ad_day", "VARCHAR(10)"),
    ("users", "ad_count_adsgram", "INTEGER DEFAULT 0"),
    ("users", "ad_count_monetag", "INTEGER DEFAULT 0"),
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
    """Make sure the schema exists — at most once per process.

    On a cold start against an existing database this used to reflect every
    table and run five ALTERs inside the request, which could blow the function
    timeout while the DB was waking up. Instead we do one cheap probe; only if
    it fails (fresh/empty DB, or a column the migrations add is missing) do we
    pay for the full create_all + migrations.
    """
    global _initialized
    if _initialized:
        return
    try:
        async with engine.connect() as conn:
            # Touches the newest migrated column too, so a DB that predates the
            # latest columns triggers a real init (running migrations) rather
            # than silently 500ing later on a query that uses them.
            await conn.execute(text("SELECT points FROM users LIMIT 1"))
        _initialized = True
        return
    except Exception:  # noqa: BLE001  (any failure -> do a full init)
        pass
    await init_db()
    _initialized = True
