"""Formatting helpers for money and wallet display."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from app.constants import USDT_QUANTIZE


def q(amount: Decimal | float | str | int) -> Decimal:
    """Quantize an amount to USDT precision (6 dp), rounding down."""
    return Decimal(str(amount)).quantize(Decimal(USDT_QUANTIZE), rounding=ROUND_DOWN)


def usdt(amount: Decimal | float | str | int) -> str:
    """Human-friendly USDT string, e.g. '1.50 USDT'."""
    value = q(amount)
    # Trim to at most 4 dp for display, but keep at least 2.
    text = f"{value:.4f}".rstrip("0")
    if text.endswith("."):
        text += "00"
    if "." not in text:
        text += ".00"
    # ensure two decimals minimum
    whole, _, frac = text.partition(".")
    if len(frac) < 2:
        frac = (frac + "00")[:2]
    return f"{whole}.{frac} USDT"


def mask_wallet(address: str) -> str:
    """0x71fc...944d style masking for public proof posts."""
    if not address or len(address) < 10:
        return address or "—"
    return f"{address[:6]}...{address[-4:]}"
