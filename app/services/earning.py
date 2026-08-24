"""Core earning logic: crediting task completions and referral rewards."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.constants import CampaignStatus
from app.db.base import Session
from app.db.models import Campaign, TaskCompletion, User
from app.utils.format import q

log = logging.getLogger(__name__)


@dataclass
class TaskResult:
    ok: bool
    reward: Decimal = Decimal("0")
    message: str = ""
    referral_bonus_to: int | None = None      # referrer id newly credited
    referral_bonus_amount: Decimal = Decimal("0")


async def get_or_create_user(
    user_id: int, username: str | None, first_name: str | None, referred_by: int | None
) -> User:
    async with Session() as s:
        user = await s.get(User, user_id)
        if user is None:
            # Only accept a referrer that exists and isn't the user themselves.
            valid_ref = None
            if referred_by and referred_by != user_id:
                if await s.get(User, referred_by) is not None:
                    valid_ref = referred_by
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                referred_by=valid_ref,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
        else:
            # keep profile fields fresh
            changed = False
            if username != user.username:
                user.username, changed = username, True
            if first_name != user.first_name:
                user.first_name, changed = first_name, True
            if changed:
                await s.commit()
        return user


async def complete_task(user_id: int, campaign_id: int) -> TaskResult:
    """Credit a verified task completion. Idempotent per (user, campaign)."""
    async with Session() as s:
        user = await s.get(User, user_id)
        campaign = await s.get(Campaign, campaign_id)
        if user is None or campaign is None:
            return TaskResult(False, message="Task not found.")
        if user.is_banned:
            return TaskResult(False, message="Your account is restricted.")
        if campaign.status != CampaignStatus.ACTIVE.value:
            return TaskResult(False, message="This task is no longer active.")

        # Already completed?
        existing = await s.scalar(
            select(TaskCompletion).where(
                TaskCompletion.user_id == user_id,
                TaskCompletion.campaign_id == campaign_id,
            )
        )
        if existing is not None:
            return TaskResult(False, message="You've already completed this task. ✅")

        reward = q(campaign.reward_per_task)
        if campaign.budget_remaining < reward:
            campaign.status = CampaignStatus.COMPLETED.value
            await s.commit()
            return TaskResult(False, message="This campaign's budget is fully claimed.")

        # Credit user + decrement campaign budget atomically.
        s.add(TaskCompletion(user_id=user_id, campaign_id=campaign_id, reward=reward))
        user.balance = q(user.balance + reward)
        user.total_earned = q(user.total_earned + reward)
        campaign.budget_remaining = q(campaign.budget_remaining - reward)
        if campaign.budget_remaining <= 0:
            campaign.status = CampaignStatus.COMPLETED.value

        result = TaskResult(True, reward=reward, message="Reward credited!")

        # Referral: credit the referrer once, on the user's FIRST completed task.
        # Blocked only when THIS account is flagged (over the per-IP allowance).
        if user.referred_by and not user.referral_credited:
            referrer = await s.get(User, user.referred_by)
            if user.flagged:
                user.referral_credited = True  # don't re-check later
                referrer = None
            if referrer is not None and not referrer.is_banned:
                bonus = q(settings.referral_reward)
                referrer.balance = q(referrer.balance + bonus)
                referrer.total_earned = q(referrer.total_earned + bonus)
                referrer.referral_earned = q(referrer.referral_earned + bonus)
                user.referral_credited = True
                result.referral_bonus_to = referrer.id
                result.referral_bonus_amount = bonus

        await s.commit()
        return result
