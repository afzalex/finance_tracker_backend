# Finance Tracker — Backend

Python backend for the Finance Tracker project. Comprises two things:

1. **CLI ingestion tool** — fetches emails from Gmail, classifies them, parses transactions, and writes to SQLite.
2. **REST API** — read-only FastAPI service that surfaces the ledger data for the frontend.

---

## Requirements

- Python 3.11+ (3.13 recommended)
- A Google Cloud project with the Gmail API enabled and an OAuth2 Desktop credentials JSON

---

## Setup

All commands below are run from inside the `backend/` directory.

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install the package

This registers the `backend` package in the venv so the CLI works from any directory:

```bash
pip install -e .
```

### 4. Configure environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/finance.db` | SQLite DB path |
| `GMAIL_CREDENTIALS_FILE` | `secrets/credentials.json` | OAuth2 client secret JSON from Google Cloud Console |
| `GMAIL_TOKEN_FILE` | `secrets/token.json` | Token file written after first login |
| `GMAIL_LABEL` | `Finance` | Gmail label to restrict ingestion to |
| `POLL_SECONDS` | `300` | Interval between Gmail polls in daemon mode |
| `INITIAL_LOOKBACK_DAYS` | `30` | Look-back window on first ingest run |
| `CONFIDENCE_THRESHOLD` | `50` | Minimum parse confidence (0–100) to accept a transaction |
| `ENV` | `development` | Runtime environment label (`development` or `production`) |
| `LOG_LEVEL` | `INFO` | Log verbosity: DEBUG, INFO, WARNING, ERROR |

### 5. Authenticate with Gmail

Download your OAuth2 Desktop client secret from Google Cloud Console
(APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop app)
and save it to `secrets/credentials.json`. Then run:

```bash
python -m backend.cli auth
```

This opens a browser window for Google sign-in. After you grant access, the token is saved to `secrets/token.json` and subsequent runs will refresh it automatically.

### 6. Run database migrations

```bash
alembic upgrade head
```

---

## CLI Usage

```bash
python -m backend.cli <command> [options]
```

### `auth` — authenticate with Gmail

```bash
python -m backend.cli auth
```

Run once on first setup, or again if the token expires and cannot be refreshed automatically.

### `ingest` — fetch and store transactions

```bash
# Default: incremental fetch from stored cursor
python -m backend.cli ingest

# Fetch only the 10 most recent messages (cursor not updated)
python -m backend.cli ingest --once 10

# Force-fetch the last 30 days, ignoring stored cursor
python -m backend.cli ingest --force

# Re-process from locally cached emails (no Gmail API call)
python -m backend.cli ingest --offline
```

### `poll` — continuous daemon mode

```bash
python -m backend.cli poll
```

Runs `ingest` on a loop, sleeping `POLL_SECONDS` between runs. Send `SIGTERM` to stop.

### `stats` — monthly summary

```bash
python -m backend.cli stats
python -m backend.cli stats --month 2026-02
```

### `export` — CSV export

```bash
python -m backend.cli export --from 2026-01-01 --to 2026-01-31 --out transactions.csv
```

### `unparsed` — inspect failed messages

```bash
python -m backend.cli unparsed --list
python -m backend.cli unparsed --show <mail_id>
```

---

## API Server

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/transactions` | Paginated, filterable transaction list |
| `GET` | `/api/v1/accounts` | All known accounts / cards / wallets |
| `GET` | `/api/v1/stats` | Monthly debit / credit / net totals |
| `GET` | `/api/v1/analytics/cashflow` | Monthly income vs expense over N months |
| `GET` | `/api/v1/analytics/category-breakdown` | Spend by category |
| `GET` | `/api/v1/analytics/top-merchants` | Top merchants by total spend |
| `GET` | `/api/v1/analytics/recurring` | Recurring transaction detection |
| `GET` | `/api/v1/analytics/anomalies` | Unusual spend highlights |
| `GET` | `/health` | Health check |

---

## Docker

Build and run via the project-root `docker-compose.yml`:

```bash
docker compose up --build
```

The API is exposed on port `8000`. The SQLite database is persisted to `./data/finance.db` on the host.

---

## Project Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI app factory
│   ├── models/          # SQLAlchemy ORM models
│   ├── routers/         # FastAPI route handlers
│   ├── schemas/         # Pydantic request/response schemas
│   └── services/        # Business logic (analytics, stats, export)
├── ingestion/
│   ├── gmail/           # Gmail OAuth client
│   ├── parsers/         # Per-issuer transaction parsers
│   ├── classifier.py    # DB-driven email classifier
│   └── pipeline.py      # Ingest orchestrator
├── migrations/          # Alembic migration scripts
├── cli.py               # CLI entry point
├── config.py            # Pydantic settings
├── database.py          # SQLAlchemy engine + session
├── pyproject.toml       # Package definition (run pip install -e . once)
├── Dockerfile
└── requirements.txt
```

---

## Adding a New Parser

1. Create a module under `backend/ingestion/parsers/`.
2. Implement the parser logic (sender/subject/body match + field extraction).
3. Register it in the parsers registry or insert a row into the `parsers` table.
4. Add a fixture and unit test.

---

## Database Migrations

```bash
# Generate a new migration after changing ORM models
alembic revision --autogenerate -m "describe change"

# Apply all pending migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```
