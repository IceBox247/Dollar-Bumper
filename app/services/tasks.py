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


def clean_task_url(channel: str | None, link: str | None) -> str:
    """Best URL for a task: the (sanitized) link, else the channel's t.me link."""
    if link:
        return link.strip().strip("<>").strip().rstrip("<>.,")
    return f"https://t.me/{channel.lstrip('@')}" if channel else ""


# Titles that mean "we couldn't name it" — safe to re-derive from the URL.
_GENERIC_TITLES = {"", "Open link"}


def display_title(channel: str | None, link: str | None, stored_title: str | None) -> str:
    """A friendly task label. Keeps a real stored/advertiser title, but re-derives
    a name+verb ("Join @X", "Follow on WhatsApp") when the stored one is generic —
    fixes tasks saved before links classified correctly, without a re-add."""
    if stored_title and stored_title not in _GENERIC_TITLES:
        return stored_title
    url = clean_task_url(channel, link)
    if url:
        return classify(url)[3]
    return stored_title or "Open link"


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


async def reverify_channel_tasks(bot) -> tuple[int, list[str]]:
    """Upgrade existing tasks whose link is a public Telegram channel back to
    verified 'channel' kind (in place, keeping completions). Returns
    (upgraded_count, channels_where_bot_is_not_admin)."""
    from app.services.membership import bot_can_verify

    upgraded = 0
    cant: list[str] = []
    async with Session() as s:
        rows = list((await s.scalars(select(Campaign))).all())
        for c in rows:
            url = clean_task_url(c.channel, c.link)
            if not url:
                continue
            kind, ch, _ln, _title = classify(url)
            if kind != "channel" or not ch:
                continue  # bots, private invites, websites — not verifiable
            if await bot_can_verify(bot, ch):
                if c.kind != "channel" or c.channel != ch or c.link:
                    c.kind = "channel"
                    c.channel = ch
                    c.link = None
                    upgraded += 1
            else:
                cant.append(ch)
        await s.commit()
    return upgraded, cant


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
