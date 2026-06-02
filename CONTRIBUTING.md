# Contributing

This repo is open to read, but active development happens with a small trusted group who have direct access to the Supabase DSN. If that's you, you'll either have push access on the main repo or you'll work from a fork — either is fine.

## Prerequisites

- Python 3.13 (Windows only — MetaTrader5 package requires Windows)
- Node.js 20+
- MetaTrader5 terminal installed and logged in
- The contributor Supabase DSN (the owner will have shared this in the group)

---

## Local Development Setup

### 1. Clone

If you have push access:

```bash
git clone https://github.com/iTermy/MT5-Auto-Execution-Bot
cd MT5-Auto-Execution-Bot
pip install -r requirements.txt
```

Otherwise fork on GitHub first, clone your fork, and add `upstream`:

```bash
git remote add upstream https://github.com/iTermy/MT5-Auto-Execution-Bot
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

### Branches and commits

Topic branch off `main`, one logical change per branch:

```bash
git checkout -b fix/short-description
```

If you forked, rebase on `upstream/main` rather than merging it in. Commit messages: imperative mood (`Add foo`, not `Added foo`), with a body that explains the *why* if it isn't obvious from the diff.

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

Open the PR against `iTermy/MT5-Auto-Execution-Bot:main`. The description should cover what changed, why, and how you tested it — short is fine. If the change touches the sync loop, TP engine, or order placer, call that out so it gets a closer look.

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
