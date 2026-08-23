"""Input validation helpers."""
from __future__ import annotations

import re

from web3 import Web3

_TG_USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{4,32}$")


def is_valid_evm_address(address: str) -> bool:
    """True if the string is a well-formed EVM/BEP20 address (checksum-agnostic)."""
    if not isinstance(address, str):
        return False
    address = address.strip()
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
        return False
    return Web3.is_address(address)


def to_checksum(address: str) -> str:
    return Web3.to_checksum_address(address.strip())


def normalize_channel(raw: str) -> str | None:
    """Normalize a channel handle or t.me link to an @username. None if invalid."""
    if not raw:
        return None
    raw = raw.strip()
    # extract from t.me links
    m = re.search(r"t\.me/([A-Za-z0-9_]{4,32})", raw)
    if m:
        raw = m.group(1)
    if _TG_USERNAME_RE.fullmatch(raw):
        return raw if raw.startswith("@") else f"@{raw}"
    return None


def is_valid_tx_hash(tx: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{64}", (tx or "").strip()))
