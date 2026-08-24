"""Input validation helpers.

Deliberately dependency-free (no web3 import) so importing this module — and
therefore the whole bot dispatcher — stays fast on serverless cold starts.
The chain layer applies EIP-55 checksumming at payout time.
"""
from __future__ import annotations

import re

_TG_USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{4,32}$")
_EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_valid_evm_address(address: str) -> bool:
    """True if the string is a well-formed EVM/BEP20 address (format check)."""
    if not isinstance(address, str):
        return False
    return bool(_EVM_ADDR_RE.fullmatch(address.strip()))


def to_checksum(address: str) -> str:
    """Normalize for storage. We keep the address as provided (trimmed); the
    payout path checksums it when building the transaction."""
    return address.strip()


def normalize_channel(raw: str) -> str | None:
    """Normalize a channel handle or t.me link to an @username. None if invalid."""
    if not raw:
        return None
    raw = raw.strip()
    m = re.search(r"t\.me/([A-Za-z0-9_]{4,32})", raw)
    if m:
        raw = m.group(1)
    if _TG_USERNAME_RE.fullmatch(raw):
        return raw if raw.startswith("@") else f"@{raw}"
    return None


def is_valid_tx_hash(tx: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{64}", (tx or "").strip()))
