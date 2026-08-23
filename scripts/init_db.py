"""Create database tables. Run once before the first deploy (and after model
changes) against your production DATABASE_URL:

    python -m scripts.init_db
"""
from __future__ import annotations

import asyncio

from app.db.base import init_db


async def main() -> None:
    await init_db()
    print("✅ Database schema created / up to date.")


if __name__ == "__main__":
    asyncio.run(main())
