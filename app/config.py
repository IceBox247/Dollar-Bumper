"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fallbacks used when an economics env var is present but left blank.
_DECIMAL_DEFAULTS = {
    "referral_reward": Decimal("0.01"),
    "min_withdrawal": Decimal("1.0"),
    "review_threshold": Decimal("5.0"),
    "min_campaign_budget": Decimal("10.0"),
}

# Fallbacks for string settings that must never be empty.
_STR_DEFAULTS = {
    "bsc_rpc_url": "https://bsc-dataseed.binance.org",
    "usdt_contract": "0x55d398326f99059fF775485246999027B3197955",
    "explorer_tx_url": "https://bscscan.com/tx/",
    "database_url": "sqlite+aiosqlite:///data/dollar_bumper.db",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    bot_token: str
    # Optional: the bot's @username (without @). If set, the Mini App skips a
    # live getMe call on every cold start when building referral links.
    bot_username: str = ""
    # Stored as raw strings; parsed into lists via the properties below.
    # (pydantic-settings JSON-parses list-typed env vars before validators run.)
    admin_ids_raw: str = Field(default="", validation_alias="ADMIN_IDS")
    # Channel where paid-withdrawal proofs are posted. Override via PROOF_CHANNEL_ID
    # (a @username or numeric -100… id). Defaults to the Dollar Bumper Payout channel.
    proof_channel_id: str = "-1003945413444"
    required_channels_raw: str = Field(default="", validation_alias="REQUIRED_CHANNELS")

    # Chain
    bsc_rpc_url: str = "https://bsc-dataseed.binance.org"
    usdt_contract: str = "0x55d398326f99059fF775485246999027B3197955"
    payout_wallet_address: str = ""
    payout_wallet_private_key: str = ""
    project_wallet_address: str = ""
    explorer_tx_url: str = "https://bscscan.com/tx/"

    # Economics (USDT)
    referral_reward: Decimal = Decimal("0.01")
    min_withdrawal: Decimal = Decimal("1.0")
    review_threshold: Decimal = Decimal("5.0")
    min_campaign_budget: Decimal = Decimal("10.0")
    # Share of an advertiser's payment that funds tasker rewards. 0.40 = 40% to
    # taskers, 60% platform fee. Accepts 0.40 or 40.
    advertiser_reward_pool_pct: Decimal = Decimal("0.40")
    # Flag an account when this many OTHER accounts already share its IP.
    # 2 = allow up to 2 accounts per IP, flag the 3rd+ (tolerant of shared/NAT).
    ip_flag_threshold: int = 2

    # Storage
    database_url: str = "sqlite+aiosqlite:///data/dollar_bumper.db"

    # Webhook / serverless (Vercel)
    webhook_secret: str = ""      # shared secret Telegram echoes back in a header
    cron_secret: str = ""         # Vercel injects this as a Bearer token on cron calls
    public_base_url: str = ""     # e.g. https://dollar-bumper.vercel.app

    @field_validator(
        "referral_reward", "min_withdrawal", "review_threshold", "min_campaign_budget",
        mode="before",
    )
    @classmethod
    def _blank_decimal_to_default(cls, v, info):
        if isinstance(v, str):
            # Tolerate values like "$0.01", "1,0", "5 USDT".
            cleaned = (
                v.replace("$", "").replace(",", ".").replace("USDT", "").strip()
            )
            if cleaned == "":
                return _DECIMAL_DEFAULTS[info.field_name]
            return cleaned
        if v is None:
            return _DECIMAL_DEFAULTS[info.field_name]
        return v

    @field_validator(
        "bsc_rpc_url", "usdt_contract", "explorer_tx_url", "database_url",
        mode="before",
    )
    @classmethod
    def _blank_str_to_default(cls, v, info):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return _STR_DEFAULTS[info.field_name]
        return v.strip() if isinstance(v, str) else v

    @field_validator("proof_channel_id", mode="before")
    @classmethod
    def _proof_default(cls, v):
        # A blank/whitespace env value must not wipe out the default channel.
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return "-1003945413444"
        return v.strip() if isinstance(v, str) else v

    @field_validator("advertiser_reward_pool_pct", mode="before")
    @classmethod
    def _pool_pct(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return Decimal("0.40")
        try:
            d = Decimal(str(v).replace("%", "").strip())
        except (InvalidOperation, ValueError):
            return Decimal("0.40")
        if d > 1:  # given as a percentage like "40"
            d = d / Decimal("100")
        if d < 0 or d > 1:
            return Decimal("0.40")
        return d

    @field_validator("ip_flag_threshold", mode="before")
    @classmethod
    def _int_default(cls, v):
        try:
            return max(1, int(str(v).strip()))
        except (ValueError, AttributeError):
            return 1

    @property
    def admin_ids(self) -> list[int]:
        return [int(x.strip()) for x in self.admin_ids_raw.split(",") if x.strip().isdigit()]

    @property
    def required_channels(self) -> list[str]:
        return [x.strip() for x in self.required_channels_raw.split(",") if x.strip()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
