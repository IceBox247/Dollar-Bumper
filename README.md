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
│   ├── storage.py      # DB-backed FSM storage (survives serverless invocations)
│   └── handlers/       # start, wallet, tasks, referral, withdraw, advertiser, admin
├── runtime.py          # shared bot/dispatcher; process_update + confirm
api/
├── webhook.py          # Vercel: Telegram webhook function
└── cron.py             # Vercel: payout-confirmation cron function
scripts/
├── init_db.py          # create tables (run once)
└── set_webhook.py      # register/delete the Telegram webhook
run.py                  # long-polling entrypoint (always-on hosts)
vercel.json             # functions + cron config
```

## Setup

1. **Create the bot** with [@BotFather](https://t.me/BotFather) and copy the token.
2. **Create channels** and add the bot as an **admin** of each:
   - [@dollarbumperpayout](https://t.me/dollarbumperpayout) — payout proof feed (`PROOF_CHANNEL_ID`)
   - [@dollarbumper](https://t.me/dollarbumper) — join-gate channel (`REQUIRED_CHANNELS`)
3. **Fund a hot wallet** with USDT (for payouts) + a little BNB (for gas).
   Keep only what you can afford to expose — sweep excess to cold storage.

### Option A — always-on host (Railway / Render / VPS) — long polling

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in real values
python run.py
```

### Option B — Vercel (serverless webhook)

Vercel can't run a long-lived poller or wait on a tx receipt, so this project
ships a **webhook** function + a **cron** confirmer and uses **Postgres**.

**1. Database (Postgres).** Create a free DB (Neon / Supabase / Vercel Postgres)
and set `DATABASE_URL`, e.g.
`postgresql+asyncpg://USER:PASS@HOST/DB?sslmode=require`.

**2. Import the repo into Vercel.** In the import screen set
**Framework Preset → Other** (not "Python"), leave the root directory as `./`.
The functions in `api/` are deployed automatically.

**3. Environment variables** (Vercel → Project → Settings → Environment Variables):
add everything from `.env.example` — `BOT_TOKEN`, `ADMIN_IDS`,
`PROOF_CHANNEL_ID`, `REQUIRED_CHANNELS`, wallet keys, economics, `DATABASE_URL`,
`WEBHOOK_SECRET` (any long random string), `PUBLIC_BASE_URL`
(`https://<your-app>.vercel.app`), and `CRON_SECRET` (any random string —
Vercel sends it to `/api/cron`).

**4. Create the tables once** (locally, pointing at the prod DB):

```bash
DATABASE_URL="postgresql+asyncpg://…?sslmode=require" python -m scripts.init_db
```

**5. Deploy**, then register the webhook (locally, with the same env):

```bash
python -m scripts.set_webhook          # -> https://<app>.vercel.app/api/webhook
```

Visit `https://<app>.vercel.app/api/webhook` — it should say
*"Dollar Bumper webhook is up."* Message your bot and you're live.

> **Hobby-plan note:** Vercel Cron runs only **once/day** on Hobby and functions
> cap at **10s**. That's fine here: payouts are *broadcast* instantly (well under
> 10s) and *confirmed* both by the daily cron **and opportunistically on user
> traffic**, so proof posts/notifications land as soon as anyone uses the bot.
> Upgrade to Pro and lower the cron `schedule` in `vercel.json` for near-instant
> confirmation.

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
