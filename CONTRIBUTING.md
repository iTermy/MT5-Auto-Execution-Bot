# Contributing

## Prerequisites

- Python 3.13 (Windows only — MetaTrader5 package requires Windows)
- Node.js 20+
- MetaTrader5 terminal installed and logged in
- Access to the contributor Supabase DSN (ask the owner)

---

## Local Development Setup

### 1. Fork and clone

Fork the repo on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-username>/MT5-Auto-Execution-Bot
cd MT5-Auto-Execution-Bot
git remote add upstream https://github.com/iTermy/MT5-Auto-Execution-Bot
pip install -r requirements.txt
```

### 2. Create your `.env` file

```bash
copy .env.example .env
```

Then fill in `SUPABASE_DSN` (ask the owner). `LICENSE_API_URL` can be left empty — the bot runs in dev-bypass mode and skips license validation when the URL is absent.

### 3. Create `config.json`

```bash
copy config.example.json config.json
```

Edit `config.json` as needed. The defaults work for standard ICMarkets accounts.

### 4. Run the backend

```bash
python main.py
```

The bot opens `http://localhost:8501` in your browser on startup.

### 5. Run the frontend in dev mode (optional)

The production frontend is served by FastAPI from `frontend/dist/`. For live-reload development:

```bash
cd frontend
npm install
npm run dev
```

Vite runs on `:5173` and proxies `/api/*` to FastAPI at `:8501`.

---

## Contribution Workflow

### Branches

Work on a topic branch off `main`:

```bash
git checkout -b fix/short-description
```

Keep branches focused — one logical change per PR. Rebase on `upstream/main` before opening a PR rather than merging it in.

### Before you push

Run the full check locally — CI is not yet wired up, so the PR review is the first place these get caught:

```bash
ruff check bot tests main.py        # lint
ruff format bot tests main.py       # format
pytest                              # backend tests
cd frontend && npx tsc --noEmit && npm run format:check && npm run build
```

All four must pass. New behaviour needs a test in `tests/` mirroring the source path (e.g. `bot/trading/foo.py` → `tests/test_foo.py`).

### Pull requests

Open the PR against `iTermy/MT5-Auto-Execution-Bot:main`. The description should answer:

1. **What** changed (one or two sentences).
2. **Why** — the bug, missing feature, or constraint that drove it.
3. **How it was tested** — which tests cover it, any manual MT5 smoke-testing you did.

Small, well-scoped PRs get merged fastest. If a change touches the trading loop, the TP engine, or the order placer, flag it explicitly in the PR description so it gets extra review.

### Issues

Use GitHub Issues for:

- **Bugs** — include MT5 broker, signal type, what you expected, what happened, and relevant lines from `bot.log`.
- **Feature requests** — describe the problem first, then a proposed solution. Avoid solution-first issues unless the design is trivial.
- **Questions about behaviour** — fine to ask, but check `ARCHITECTURE.md` and `CLAUDE.md` first.

Don't open a PR for a non-trivial change without an issue or prior discussion — alignment first saves rework.

### Commits

- Imperative mood: `Add foo`, not `Added foo`.
- One logical change per commit.
- Body explains the *why* if it's not obvious from the diff.

---

## Key Constraints (Read Before Coding)

- Supabase tables (`signals`, `limits`, `live_prices`, `licenses`, `bot_mode_status`, `feed_health`) are **read-only** from the bot. The only Supabase write the bot performs is `INSERT` on `tp_outcomes`.
- All other mutable state lives in local SQLite (`orders.db`).
- MT5 calls are synchronous and bound to the engine thread. Never call MT5 from a FastAPI handler.
- Magic number `20250001` identifies all bot orders in MT5.
- See `ARCHITECTURE.md` for the full system design and `CLAUDE.md` for code conventions.
