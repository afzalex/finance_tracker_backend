# Finance Tracker Backend

## Objective
The modern Python backend for the Finance Tracker application. It comprises a CLI ingestion engine and a RESTful API meant to act as the primary brain for the financial tracker, fetching categorized records from emails and providing analytics endpoints.

## Core Functions
1. **CLI Ingestion (`backend.cli`):**
   - Retrieves transaction alerts from Gmail API.
   - Classifies message types and parses text to extract transaction fields.
   - Saves final normalized transactions to an SQLite `finance.db`.
2. **REST API (`app/main.py`):**
   - Built on FastAPI.
   - Provides HTTP endpoints (`/api/v1/transactions`, `/api/v1/stats`, etc.) to surface stored data.

## Execution
- Commands run out of a virtual environment (`python -m venv .venv`).
- Requires properly formatted `.env` providing DB path and Gmail tokens/secrets.
