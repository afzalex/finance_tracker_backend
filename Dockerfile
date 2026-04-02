FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ backend/
COPY .env.example .env.example

# Run alembic from backend/ (where alembic.ini lives); PYTHONPATH keeps 'import backend' working
WORKDIR /app/backend
ENV PYTHONPATH=/app
CMD ["sh", "-c", "mkdir -p data && alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
