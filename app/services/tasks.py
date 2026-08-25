"""Admin-created earn tasks (channels to join / links to visit)."""
from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import CampaignStatus
from app.db.base import Session
from app.db.models import Campaign
from app.utils.format import q

_UNAME = r"[A-Za-z0-9_]{4,32}"
_BIG_BUDGET = Decimal("1000000")


def classify(url: str) -> tuple[str, str | None, str | None, str]:
    """Return (kind, channel, link, title) for a task URL.

    kind == "channel" → a public t.me/<name> we can check membership for.
    kind == "visit"   → anything else (bot start links, mini-apps, private
                        invites, external URLs, WhatsApp / YouTube / X / any
                        website): open + claim.

    Accepts a full URL, a bare ``@username``, or a bare ``username`` and treats
    those as a public Telegram channel.
    """
    # Strip surrounding <> (Telegram/markdown auto-links) and trailing junk so a
    # pasted "<https://t.me/x>" doesn't classify as a broken "Open link".
    url = url.strip().strip("<>").strip().rstrip("<>")
    # Bare @username or username -> treat as a Telegram channel link.
    if re.fullmatch(r"@?[A-Za-z0-9_]{4,32}", url):
        return "channel", f"@{url.lstrip('@')}", None, f"Join @{url.lstrip('@')}"
    if re.search(r"t\.me/\+", url):  # private invite link
        return "visit", None, url, "Join private group"
    m = re.search(r"t\.me/(" + _UNAME + r")(\?\S*)?$", url)
    if m:
        name, query = m.group(1), (m.group(2) or "")
        if "start=" in query or "startapp=" in query:
            return "visit", None, url, f"Open @{name}"
        return "channel", f"@{name}", None, f"Join @{name}"
    low = url.lower()
    if "whatsapp.com" in low or "wa.me" in low:
        return "visit", None, url, "Follow on WhatsApp"
    if "youtube.com" in low or "youtu.be" in low:
        return "visit", None, url, "Subscribe on YouTube"
    if "x.com" in low or "twitter.com" in low:
        return "visit", None, url, "Follow on X"
    return "visit", None, url, "Open link"


async def create_task(
    kind: str, title: str, channel: str | None, link: str | None,
    reward: Decimal, admin_id: int,
) -> Campaign:
    async with Session() as s:
        c = Campaign(
            advertiser_id=admin_id,
            title=title[:128],
            channel=(channel or "")[:64],
            reward_per_task=q(reward),
            budget_total=q(_BIG_BUDGET),
            budget_remaining=q(_BIG_BUDGET),
            status=CampaignStatus.ACTIVE.value,
            kind=kind,
            link=link,
        )
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c


async def delete_task(task_id: int) -> bool:
    async with Session() as s:
        c = await s.get(Campaign, task_id)
        if c is None:
            return False
        await s.delete(c)
        await s.commit()
        return True


async def all_tasks() -> list[Campaign]:
    async with Session() as s:
        rows = await s.scalars(select(Campaign).order_by(Campaign.id.desc()))
        return list(rows.all())


async def clear_all_tasks() -> int:
    """Delete every task/campaign (and its completion rows). Returns count removed.

    Completions are deleted first to satisfy the campaign foreign key.
    """
    from sqlalchemy import delete

    from app.db.models import TaskCompletion

    async with Session() as s:
        n = await s.scalar(select(func.count(Campaign.id)))
        await s.execute(delete(TaskCompletion))
        await s.execute(delete(Campaign))
        await s.commit()
        return int(n or 0)
