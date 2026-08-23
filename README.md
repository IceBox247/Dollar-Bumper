# 💵 Dollar Bumper

A **real** paid-advertising marketplace on Telegram.

- **Advertisers** pay (in USDT, BEP20) to feature their channel.
- **Users** get paid real USDT for completing quick tasks (joining featured
  channels) and for referring friends.
- **Withdrawals are non-conditional** and paid **on-chain** — small amounts
  auto-pay instantly, larger ones get a quick anti-fraud review first.
- Every real payout is posted to a **public proof channel** with a live
  BscScan transaction link.

> This is honest by design: users are paid from advertiser revenue, terms are
> transparent, and there are **no fake payout screenshots, no forced-join
> farming, and no data-harvesting "IP checks."** If you fork this, keep it that
> way — pay people what you promise.

---

## How it works

```
Advertiser  ──pays USDT──▶  Project wallet ──(auto-verified on-chain)──▶ Campaign goes LIVE
                                                                              │
User ──joins featured channel──▶ bot verifies membership ──▶ balance credited │
   │                                                                          │
   └──invites friend──▶ friend completes first task ──▶ referrer gets bonus ──┘
                                                                              │
User ──Withdraw──▶ < $5 auto-pays on-chain │ ≥ $5 admin review ──▶ pays ──▶ Proof channel post
```

## Tech stack

| Concern        | Choice                                  |
| -------------- | --------------------------------------- |
| Bot framework  | [aiogram](https://aiogram.dev) v3       |
| Blockchain     | [web3.py](https://web3py.readthedocs.io) — BNB Smart Chain, BEP20 USDT |
| Storage        | SQLAlchemy 2.0 async + SQLite (swap `DATABASE_URL` for Postgres) |
| Config         | pydantic-settings (`.env`)              |

## Project layout

```
app/
├── config.py           # env-driven settings
├── constants.py        # status enums
├── db/                 # engine, models, schema init
├── services/
│   ├── chain.py        # web3: USDT transfer, payment verification, balances
│   ├── earning.py      # task completion + referral crediting
│   ├── campaigns.py    # advertiser campaign lifecycle + on-chain verify
│   ├── payouts.py      # withdrawal → review/auto-pay → proof post
│   └── membership.py   # channel-join verification
├── bot/
│   ├── ui.py           # message text
│   ├── keyboards.py    # inline + reply keyboards
│   ├── states.py       # FSM
│   └── handlers/       # start, wallet, tasks, referral, withdraw, advertiser, admin
run.py                  # entrypoint
```

## Setup

1. **Create the bot** with [@BotFather](https://t.me/BotFather) and copy the token.
2. **Create a proof/payments channel**, add the bot as an **admin** (post rights).
3. **Fund a hot wallet** with USDT (for payouts) + a little BNB (for gas).
   Keep only what you can afford to expose — sweep excess to cold storage.
4. Configure and run:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in real values
python run.py
```

## Configuration (`.env`)

See `.env.example` for the full list. Key values:

| Var | Meaning |
| --- | --- |
| `BOT_TOKEN` | From @BotFather |
| `ADMIN_IDS` | Comma-separated Telegram user IDs with admin rights |
| `PROOF_CHANNEL_ID` | `@channel` (bot must be admin) for payout proofs |
| `PAYOUT_WALLET_ADDRESS` / `PAYOUT_WALLET_PRIVATE_KEY` | Hot wallet that pays users |
| `PROJECT_WALLET_ADDRESS` | Receives advertiser payments (can be cold) |
| `REFERRAL_REWARD`, `MIN_WITHDRAWAL`, `REVIEW_THRESHOLD`, `MIN_CAMPAIGN_BUDGET` | Economics, in USDT |

## Admin commands

- `/stats` — users, active campaigns, total paid, pending reviews
- `/fund` — payout wallet USDT + BNB balances (warns on low gas)
- `/pending` — list withdrawals awaiting review, approve/reject inline
- `/ban <id>` · `/unban <id>`

## Security notes

- The payout private key is a **hot key**. Fund it minimally, monitor `/fund`,
  and keep the review threshold sensible. Consider a dedicated node/RPC for scale.
- Advertiser payments are verified by summing the USDT `Transfer` events to the
  project wallet in the given tx, and each tx hash can only fund one campaign.
- Withdrawals deduct the balance **before** sending and **refund on failure**,
  so a failed/reverted tx never loses user funds.
- The join-gate and channel-join tasks require the bot to be an **admin** of the
  relevant channel (Telegram only reveals membership to channel admins).

## Roadmap ideas

- Auto-verify advertiser payments via a wallet watcher (no manual tx paste)
- Postgres + Alembic migrations for production
- Per-campaign anti-sybil (device/behavior signals) instead of fake "IP checks"
- Advertiser self-serve dashboard (web) and analytics
