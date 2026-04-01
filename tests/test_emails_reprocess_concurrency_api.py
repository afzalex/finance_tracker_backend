from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_reprocess_rejects_when_job_active(db) -> None:
    client, app = _client_with_db(db)
    try:
        first = client.post("/api/v1/emails/reprocess")
        assert first.status_code == 200
        job_id = first.json()["job_id"]

        second = client.post("/api/v1/emails/reprocess")
        assert second.status_code == 409
        assert second.json()["detail"]["job_id"] == job_id
    finally:
        app.dependency_overrides.clear()

