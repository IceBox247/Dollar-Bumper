"""Shared enums and status constants."""
from __future__ import annotations

import enum


class CampaignStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"  # created, awaiting on-chain payment
    ACTIVE = "active"                    # payment verified, live for users
    PAUSED = "paused"                    # temporarily hidden
    COMPLETED = "completed"              # budget exhausted
    REJECTED = "rejected"                # rejected by admin


class WithdrawalStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"    # >= review threshold, awaiting admin
    QUEUED = "queued"                    # approved / below threshold, ready to pay
    PROCESSING = "processing"            # tx being broadcast
    PAID = "paid"                        # confirmed on-chain
    FAILED = "failed"                    # tx failed / errored
    REJECTED = "rejected"                # rejected by admin


# Money is stored with 6 decimal places of precision in the DB.
USDT_QUANTIZE = "0.000001"
