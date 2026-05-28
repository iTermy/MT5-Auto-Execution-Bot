# Contributing

## Prerequisites

- Python 3.13 (Windows only — MetaTrader5 package requires Windows)
- Node.js 20+
- MetaTrader5 terminal installed and logged in
- Access to the contributor Supabase DSN (ask the owner)

---

## Local Development Setup

### 1. Clone and install Python dependencies

```bash
git clone <repo-url>
cd MT5-Auto-Execution-Bot
pip install -r requirements.txt
```

### 2. Create your `.env` file

```
SUPABASE_DSN=postgresql://contributor_bot:PASSWORD@db.xxxxx.supabase.co:5432/postgres
LICENSE_API_URL=https://xxxxx.supabase.co/functions/v1/validate-license
```

The owner shares the contributor DSN and Edge Function URL. The `LICENSE_API_URL` can be left empty — the bot runs in dev-bypass mode and skips license validation when the URL is absent.

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

## Supabase Contributor Role

The contributor role has SELECT-only access to the required tables. Run this SQL in the Supabase SQL editor to create it:

```sql
CREATE ROLE contributor_bot WITH LOGIN PASSWORD 'initial_password';
GRANT USAGE ON SCHEMA public TO contributor_bot;
GRANT SELECT ON signals, limits, live_prices TO contributor_bot;
```

### Monthly password rotation

```sql
ALTER ROLE contributor_bot WITH PASSWORD 'new_password_here';
```

After rotating, share an updated `.env` with all active contributors.

---

## Production Build Workflow

This workflow is for the owner only. Do **not** commit the filled constants.

### 1. Fill production secrets

Edit `bot/config/constants.py` and set the real values:

```python
_PRODUCTION_DSN = "postgresql://..."
_PRODUCTION_LICENSE_URL = "https://xxxxx.supabase.co/functions/v1/validate-license"
```

### 2. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

This produces `frontend/dist/`.

### 3. Build the executable

```bash
pyinstaller bot.spec
```

The output is `dist/MT5Bot.exe` — a single-file Windows executable with the frontend bundled.

### 4. Revert constants before pushing

```bash
git checkout bot/config/constants.py
```

Never commit the filled DSN or license URL.

---

## Deploying the Edge Function

Install the Supabase CLI and log in:

```bash
npm install -g supabase
supabase login
supabase link --project-ref <your-project-ref>
```

Deploy:

```bash
supabase functions deploy validate-license
```

The Edge Function reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the project environment automatically.

### licenses table schema

```sql
CREATE TABLE licenses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_key TEXT NOT NULL UNIQUE,
    mt5_account BIGINT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT true,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Key Constraints (Read Before Coding)

- Supabase tables (`signals`, `limits`, `live_prices`, `licenses`) are **read-only** from the bot.
- All mutable state lives in local SQLite (`orders.db`).
- MT5 calls are synchronous and bound to the engine thread. Never call MT5 from a FastAPI handler.
- Magic number `20250001` identifies all bot orders in MT5.
- See `ARCHITECTURE.md` for the full system design and `STATE.md` for all implementation decisions.
