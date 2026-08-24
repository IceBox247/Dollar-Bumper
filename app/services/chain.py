"""BNB Smart Chain / BEP20 USDT interactions (synchronous web3, run in a thread)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3
from web3.middleware import geth_poa_middleware

from app.config import settings

log = logging.getLogger(__name__)

# Minimal ERC20 ABI (transfer / balanceOf / decimals + Transfer event)
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
]


@dataclass
class PaymentCheck:
    ok: bool
    amount: Decimal          # USDT amount sent to the expected recipient
    sender: str | None       # from address (checksummed) if found
    reason: str = ""         # human-readable failure reason when ok is False


class Chain:
    """Thin wrapper around a BSC web3 connection for USDT payouts and verification."""

    def __init__(self) -> None:
        # Lazy: nothing here can crash at import time even if config is off,
        # so a misconfig surfaces as a handled error at call time, not a
        # total bot outage.
        self._w3: Web3 | None = None
        self._usdt = None
        self._decimals: int | None = None

    @property
    def w3(self) -> Web3:
        if self._w3 is None:
            w3 = Web3(Web3.HTTPProvider(settings.bsc_rpc_url, request_kwargs={"timeout": 30}))
            # BSC is a PoA chain — needed to decode its block headers.
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            self._w3 = w3
        return self._w3

    @property
    def usdt(self):
        if self._usdt is None:
            self._usdt = self.w3.eth.contract(
                address=Web3.to_checksum_address(settings.usdt_contract), abi=ERC20_ABI
            )
        return self._usdt

    # ── helpers ────────────────────────────────────────────────
    def _dec(self) -> int:
        if self._decimals is None:
            try:
                self._decimals = int(self.usdt.functions.decimals().call())
            except Exception:
                self._decimals = 18  # BSC USDT is 18-decimals
        return self._decimals

    def _to_units(self, amount: Decimal) -> int:
        return int(Decimal(amount) * (Decimal(10) ** self._dec()))

    def _from_units(self, units: int) -> Decimal:
        return Decimal(units) / (Decimal(10) ** self._dec())

    # ── read ops ───────────────────────────────────────────────
    def _payout_balance_sync(self) -> Decimal:
        addr = Web3.to_checksum_address(settings.payout_wallet_address)
        return self._from_units(self.usdt.functions.balanceOf(addr).call())

    def _gas_balance_sync(self) -> Decimal:
        addr = Web3.to_checksum_address(settings.payout_wallet_address)
        return Decimal(self.w3.from_wei(self.w3.eth.get_balance(addr), "ether"))

    def _verify_payment_sync(self, tx_hash: str, expected_to: str, min_amount: Decimal) -> PaymentCheck:
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return PaymentCheck(False, Decimal("0"), None, "Transaction not found or not yet mined.")

        if receipt.get("status") != 1:
            return PaymentCheck(False, Decimal("0"), None, "Transaction failed on-chain.")

        expected = Web3.to_checksum_address(expected_to)
        total = Decimal("0")
        sender: str | None = None

        # Sum all USDT Transfer events in this tx that credit the expected wallet.
        try:
            logs = self.usdt.events.Transfer().process_receipt(receipt)
        except Exception:
            logs = []

        for ev in logs:
            args = ev["args"]
            if Web3.to_checksum_address(args["to"]) == expected:
                total += self._from_units(args["value"])
                sender = Web3.to_checksum_address(args["from"])

        if total <= 0:
            return PaymentCheck(False, Decimal("0"), None, "No USDT transfer to the project wallet in this tx.")
        if total < min_amount:
            return PaymentCheck(False, total, sender, f"Paid {total} USDT, below the required minimum.")
        return PaymentCheck(True, total, sender)

    def _broadcast_usdt_sync(self, to_address: str, amount: Decimal) -> str:
        """Sign & broadcast a USDT transfer and return the tx hash WITHOUT
        waiting for the receipt (safe for short serverless timeouts)."""
        acct = self.w3.eth.account.from_key(settings.payout_wallet_private_key)
        to_address = Web3.to_checksum_address(to_address)
        units = self._to_units(amount)

        tx = self.usdt.functions.transfer(to_address, units).build_transaction(
            {
                "from": acct.address,
                "nonce": self.w3.eth.get_transaction_count(acct.address, "pending"),
                "gas": 100_000,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            }
        )
        signed = self.w3.eth.account.sign_transaction(tx, settings.payout_wallet_private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        return tx_hash.hex()

    def _tx_status_sync(self, tx_hash: str) -> str:
        """Return 'success' | 'failed' | 'pending' for a broadcast tx."""
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return "pending"  # not mined yet (or not found)
        if receipt is None:
            return "pending"
        return "success" if receipt.get("status") == 1 else "failed"

    # ── async wrappers (web3 is blocking; keep the event loop free) ──
    async def payout_balance(self) -> Decimal:
        return await asyncio.to_thread(self._payout_balance_sync)

    async def gas_balance(self) -> Decimal:
        return await asyncio.to_thread(self._gas_balance_sync)

    async def verify_payment(self, tx_hash: str, expected_to: str, min_amount: Decimal) -> PaymentCheck:
        return await asyncio.to_thread(self._verify_payment_sync, tx_hash, expected_to, min_amount)

    async def broadcast_usdt(self, to_address: str, amount: Decimal) -> str:
        return await asyncio.to_thread(self._broadcast_usdt_sync, to_address, amount)

    async def tx_status(self, tx_hash: str) -> str:
        return await asyncio.to_thread(self._tx_status_sync, tx_hash)


chain = Chain()
