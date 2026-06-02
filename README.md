# MT5 Auto-Execution Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Windows desktop app that reads trading signals from Supabase Postgres and places/manages pending orders on MetaTrader 5 via ICMarkets. FastAPI + React dashboard at `localhost:8501`, system tray icon, single-file `.exe` build.

## What it does

- Polls Supabase for active signals and pending limits every 30 seconds.
- Places, modifies, and cancels MT5 pending orders idempotently.
- Detects fills, applies a take-profit strategy per asset class, and places trailing stops on the remainder.
- Adjusts every order for current spread and feed offset (OANDA / Binance prices vs. ICMarkets).
- Pauses around the daily 16:45–18:00 ET spread hour and across the weekend.
- Surfaces live status, positions, history, and configuration in a local web dashboard.

## Quick start

Requirements: **Windows**, **Python 3.13**, **Node.js 20+**, **MetaTrader 5** installed and logged in.

```bash
git clone https://github.com/iTermy/MT5-Auto-Execution-Bot
cd MT5-Auto-Execution-Bot

# Backend
pip install -r requirements.txt
cp .env.example .env                  # then fill in SUPABASE_DSN (ask the owner)
cp config.example.json config.json

# Frontend (production build, bundled and served by FastAPI)
cd frontend && npm install && npm run build && cd ..

# Run
python main.py
```

The bot opens `http://localhost:8501` automatically and lives in the system tray. For live-reload frontend development, use `cd frontend && npm run dev` (Vite on `:5173` with proxy to `:8501`).

## Docs

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — tech stack, concurrency model, core loops, TP engine, schemas, FastAPI endpoints.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — full setup, Supabase contributor role, production `.exe` build, license Edge Function.

## Project layout

```
bot/             Python backend
  api/             FastAPI app, routes, SSE
  config/          Pydantic settings, constants
  core/            Engine, sync cycle, reconciler, dashboard cache
  db/              asyncpg (Supabase) + aiosqlite
  license/         Edge Function client
  mt5/             MT5 client, connection, types
  tp/              TP engine, strategy, trailing
  trading/         Lot calc, offset, symbol mapping, order placer/canceller
  utils/           Logging, time helpers
frontend/        React + TypeScript + Vite SPA
supabase/        Edge Function for license validation
tests/           pytest suite
main.py          Entry point (system tray + engine thread)
bot.spec         PyInstaller build spec
```

## License

[MIT](LICENSE). The bot is provided as-is; you are responsible for your own trades.
