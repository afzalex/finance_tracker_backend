# Backend Coding Rules

When developing inside the `/backend` folder:

## Technical Requirements
- **Target runtime:** Python 3.11+
- **Strict Typing:** All FastAPI parameters, internal methods, and Pydantic models must be strictly typed.
- **Database Modifiers:** Direct changes to DB models must be accompanied by Alembic migrations. Do not manipulate SQLite schemas directly.

## Parser Development Workflow
If adding a new institution parser (e.g. tracking a new banking app):
1. **Creation:** Place it logically under `backend/ingestion/parsers/`.
2. **Logic Check:** Parse rules must successfully yield the **four mandatory transaction fields**: `amount` (numeric float), `direction` (DEBIT/CREDIT), `provider` (App/Bank name), and `account_id` (identifier/last 4).
3. **Tests:** It is highly recommended to include test fixtures and unit tests for parsers to avoid silently breaking them in future changes.

## Testing & APIs
- Validate any new endpoints (`backend/app/routers/`) with standard HTTP tools and ensure Pydantic structures (`backend/app/schemas/`) adequately constrain request/response bodies.
- Code must adhere to standard Python linters/formatters. Use descriptive exception handling when working with regex parsing.
