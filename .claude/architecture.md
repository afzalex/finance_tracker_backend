# Backend Architecture

## Directory Layout
- **`app/`**: Core API server
  - `main.py`: FastAPI factory
  - `models/`: SQLAlchemy tables (ORM)
  - `schemas/`: Pydantic request/response typed models
  - `routers/`: Endpoint controllers
  - `services/`: Business/analytics logic
- **`ingestion/`**: Email downloading and parsing engine
  - `gmail/`: OAuth integration logic
  - `parsers/`: Python-based extraction scripts representing distinct financial institutions
  - `classifier.py`: Decides what parser to use based on message type
  - `pipeline.py`: Orchestrator that bridges Gmail fetching, classifying, parsing, and committing to the DB.
- **`migrations/`**: Alembic schema definition logic for iterating DB state.
- **`cli.py`**: The unified CLI application controller.

## Database Pattern
- **Engine**: SQLite.
- Modifications require Alembic runs (`alembic revision --autogenerate`, `alembic upgrade head`).
