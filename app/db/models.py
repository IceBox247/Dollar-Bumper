"""ORM models for Dollar Bumper."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import CampaignStatus, WithdrawalStatus
from app.db.base import Base

MONEY = Numeric(precision=18, scale=6)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    total_earned: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    referral_earned: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))

    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # A referral only "counts" once the referred user completes their first task.
    referral_credited: Mapped[bool] = mapped_column(Boolean, default=False)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    advertiser_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(64))  # @username users must join
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    reward_per_task: Mapped[Decimal] = mapped_column(MONEY)
    budget_total: Mapped[Decimal] = mapped_column(MONEY)
    budget_remaining: Mapped[Decimal] = mapped_column(MONEY)

    status: Mapped[str] = mapped_column(String(24), default=CampaignStatus.PENDING_PAYMENT.value)
    payment_tx_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskCompletion(Base):
    __tablename__ = "task_completions"
    __table_args__ = (UniqueConstraint("user_id", "campaign_id", name="uq_user_campaign"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    reward: Mapped[Decimal] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    wallet_address: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(24), default=WithdrawalStatus.QUEUED.value)
    tx_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedTx(Base):
    """Guards against reusing the same advertiser payment tx across campaigns."""
    __tablename__ = "processed_txs"

    tx_hash: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
