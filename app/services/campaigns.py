"""Advertiser campaign lifecycle: create, verify on-chain payment, list."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.constants import CampaignStatus
from app.db.base import Session
from app.db.models import Campaign, ProcessedTx
from app.services.chain import chain
from app.utils.format import q

log = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    ok: bool
    message: str
    campaign_id: int | None = None
    amount: Decimal = Decimal("0")


async def create_campaign(
    advertiser_id: int,
    title: str,
    channel: str,
    reward_per_task: Decimal,
    budget_total: Decimal,
    description: str | None = None,
) -> Campaign:
    async with Session() as s:
        campaign = Campaign(
            advertiser_id=advertiser_id,
            title=title[:128],
            channel=channel,
            description=(description or "")[:1000] or None,
            reward_per_task=q(reward_per_task),
            budget_total=q(budget_total),
            budget_remaining=q(budget_total),
            status=CampaignStatus.PENDING_PAYMENT.value,
        )
        s.add(campaign)
        await s.commit()
        await s.refresh(campaign)
        return campaign


async def verify_and_activate(campaign_id: int, tx_hash: str) -> VerifyResult:
    """Verify an advertiser's USDT payment on-chain and activate the campaign."""
    tx_hash = tx_hash.strip()
    async with Session() as s:
        campaign = await s.get(Campaign, campaign_id)
        if campaign is None:
            return VerifyResult(False, "Campaign not found.")
        if campaign.status == CampaignStatus.ACTIVE.value:
            return VerifyResult(True, "Campaign is already active.", campaign_id)
        if campaign.status != CampaignStatus.PENDING_PAYMENT.value:
            return VerifyResult(False, "This campaign can't be activated.")

        # Prevent the same tx from funding multiple campaigns.
        if await s.get(ProcessedTx, tx_hash) is not None:
            return VerifyResult(False, "This transaction has already been used.")

        check = await chain.verify_payment(
            tx_hash, settings.project_wallet_address, q(campaign.budget_total)
        )
        if not check.ok:
            return VerifyResult(False, check.reason or "Payment could not be verified.")

        campaign.status = CampaignStatus.ACTIVE.value
        campaign.payment_tx_hash = tx_hash
        campaign.payment_amount = q(check.amount)
        campaign.activated_at = datetime.now(timezone.utc)
        # Credit any overpayment to the campaign's spendable budget.
        if q(check.amount) > campaign.budget_total:
            extra = q(check.amount) - campaign.budget_total
            campaign.budget_total = q(campaign.budget_total + extra)
            campaign.budget_remaining = q(campaign.budget_remaining + extra)
        s.add(ProcessedTx(tx_hash=tx_hash))
        await s.commit()
        return VerifyResult(True, "Payment verified — campaign is live! 🎉", campaign_id, check.amount)


async def active_campaigns_for(user_id: int) -> list[Campaign]:
    """Active campaigns the user has NOT yet completed, with budget remaining."""
    from app.db.models import TaskCompletion

    async with Session() as s:
        done = await s.scalars(
            select(TaskCompletion.campaign_id).where(TaskCompletion.user_id == user_id)
        )
        done_ids = set(done.all())
        rows = await s.scalars(
            select(Campaign)
            .where(
                Campaign.status == CampaignStatus.ACTIVE.value,
                Campaign.budget_remaining >= Campaign.reward_per_task,
            )
            .order_by(Campaign.reward_per_task.desc(), Campaign.id.desc())
        )
        return [c for c in rows.all() if c.id not in done_ids]


async def campaigns_by_advertiser(advertiser_id: int) -> list[Campaign]:
    async with Session() as s:
        rows = await s.scalars(
            select(Campaign)
            .where(Campaign.advertiser_id == advertiser_id)
            .order_by(Campaign.id.desc())
        )
        return list(rows.all())
