from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.database import get_db
from backend.ingestion.mail.errors import MailProviderAuthError
from backend.ingestion.pipeline import mail_force_ingest_args


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_mail_force_ingest_args() -> None:
    args = mail_force_ingest_args(lookback_days=14)
    assert args.force == -1
    assert args.lookback_days == 14
    assert args.mail is True
    assert args.once is None

    capped = mail_force_ingest_args(lookback_days=7, max_messages=50)
    assert capped.force == 50
    assert capped.lookback_days == 7


def test_mail_ingest_sync(db) -> None:
    stats = {"fetched": 3, "parsed": 2, "unparsed": 1, "skipped": 0, "duplicate": 0}
    client, app = _client_with_db(db)
    try:
        with patch("backend.app.routers.admin.run_ingest", return_value=stats) as mock_run:
            r = client.post("/api/v1/admin/mail/ingest?days=30&wait=true")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"lookback_days": 30, "stats": stats}
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args.lookback_days == 30
    assert call_args.force == -1


def test_mail_ingest_sync_auth_error(db) -> None:
    client, app = _client_with_db(db)
    try:
        with patch(
            "backend.app.routers.admin.run_ingest",
            side_effect=MailProviderAuthError("not authenticated"),
        ):
            r = client.post("/api/v1/admin/mail/ingest?days=7&wait=true")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 409
    assert "not authenticated" in r.json()["detail"]


def test_mail_ingest_async_returns_job(db) -> None:
    client, app = _client_with_db(db)
    try:
        with patch("backend.app.routers.admin.run_ingest", return_value={"fetched": 0}):
            r = client.post("/api/v1/admin/mail/ingest?days=14")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "running"
    assert data["lookback_days"] == 14
    assert "job_id" in data


def test_mail_ingest_conflict_when_running(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_JOBS["busy"] = {"status": "running", "started_at": "t"}
    try:
        r = client.post("/api/v1/admin/mail/ingest?days=3")
    finally:
        admin_router._MAIL_INGEST_JOBS.clear()
        app.dependency_overrides.clear()

    assert r.status_code == 409
    assert r.json()["detail"]["job_id"] == "busy"


def test_mail_ingest_job_status(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS["abc123"] = {
        "status": "completed",
        "started_at": "t0",
        "completed_at": "t1",
        "lookback_days": 5,
        "stats": {"fetched": 1},
    }
    try:
        r = client.get("/api/v1/admin/mail/ingest/abc123")
    finally:
        admin_router._MAIL_INGEST_JOBS.pop("abc123", None)
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["job_id"] == "abc123"
    assert r.json()["status"] == "completed"
