# Contributing

This repo is open to read. Active development happens with a small trusted group who have the Supabase DSN. If that's you, you'll work from a fork and open pull requests against this repo. The owner reviews and merges.

## Prerequisites

- Python 3.13 (Windows only — MetaTrader5 package requires Windows)
- Node.js 20+
- MetaTrader5 terminal installed and logged in
- The contributor Supabase DSN (shared in the group)

---

## Local Development Setup

### 1. Fork and clone

Fork the repo on GitHub, then clone your fork and wire up `upstream`:

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

Fill in `SUPABASE_DSN` (from the group). `LICENSE_API_URL` can be left empty — the bot runs in dev-bypass mode and skips license validation when the URL is absent.

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

### Stay in sync

Before starting a new branch, pull the latest `main` from upstream into your fork:

```bash
git fetch upstream
git checkout main
git merge --ff-only upstream/main
git push origin main
```

### Branches and commits

Topic branch off `main` on your fork, one logical change per branch:

```bash
git checkout -b fix/short-description
```

If `upstream/main` moves while you're working, rebase rather than merging it in:

```bash
git fetch upstream
git rebase upstream/main
```

Commit messages: imperative mood (`Add foo`, not `Added foo`), with a body explaining the *why* if it isn't obvious from the diff.

### Before you push

Run the full check locally — there is no CI yet, so anything you don't catch lands in review:

```bash
ruff check bot tests main.py
ruff format bot tests main.py
pytest
cd frontend && npx tsc --noEmit && npm run format:check && npm run build
```

New behaviour needs a test in `tests/` mirroring the source path (e.g. `bot/trading/foo.py` → `tests/test_foo.py`).

### Pull requests

Push your branch to your fork and open the PR against `iTermy/MT5-Auto-Execution-Bot:main`:

```bash
git push origin fix/short-description
```

The PR description should cover what changed, why, and how you tested it — short is fine. If the change touches the sync loop, TP engine, or order placer, call that out so it gets a closer look.

For non-trivial work, give the group a heads-up on the server before you start so two people aren't building the same thing.

### Issues

Use GitHub Issues for tracking bugs and feature ideas. Bug reports are most useful with: MT5 broker, signal type, what you expected vs. what happened, and the relevant lines from `bot.log`. Quick questions are better off in the group chat than as issues.

---

## Key Constraints (Read Before Coding)

- Supabase tables (`signals`, `limits`, `live_prices`, `licenses`, `bot_mode_status`, `feed_health`) are **read-only** from the bot. The only Supabase write the bot performs is `INSERT` on `tp_outcomes`.
- All other mutable state lives in local SQLite (`orders.db`).
- MT5 calls are synchronous and bound to the engine thread. Never call MT5 from a FastAPI handler.
- Magic number `20250001` identifies all bot orders in MT5.
- See `ARCHITECTURE.md` for the full system design and `CLAUDE.md` for code conventions.
