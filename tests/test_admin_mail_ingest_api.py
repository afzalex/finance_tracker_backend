from __future__ import annotations

import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.database import get_db
from backend.ingestion.mail.errors import MailProviderAuthError
from backend.ingestion.pipeline import IngestCancelled, mail_force_ingest_args


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
    body = r.json()
    assert body["lookback_days"] == 30
    assert body["stats"]["fetched"] == 3
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


def test_mail_ingest_status_idle(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_CANCEL.clear()
    try:
        r = client.get("/api/v1/admin/mail/ingest/status")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"in_progress": False, "job": None}


def test_mail_ingest_status_in_progress(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_JOBS["busy"] = {
        "status": "running",
        "started_at": "t0",
        "lookback_days": 10,
    }
    try:
        r = client.get("/api/v1/admin/mail/ingest/status")
    finally:
        admin_router._MAIL_INGEST_JOBS.clear()
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["in_progress"] is True
    assert data["job"]["job_id"] == "busy"
    assert data["job"]["status"] == "running"
    assert data["job"]["lookback_days"] == 10


def test_mail_ingest_conflict_when_running(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_JOBS["busy"] = {
        "status": "running",
        "started_at": "t0",
        "lookback_days": 3,
    }
    try:
        r = client.post("/api/v1/admin/mail/ingest?days=3")
    finally:
        admin_router._MAIL_INGEST_JOBS.clear()
        app.dependency_overrides.clear()

    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["message"] == "Ingestion already in progress"
    assert detail["job_id"] == "busy"
    assert detail["status"] == "running"


def test_mail_ingest_cancel_running_job(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_CANCEL.clear()
    ev = threading.Event()
    admin_router._MAIL_INGEST_JOBS["j1"] = {
        "status": "running",
        "started_at": "t0",
        "lookback_days": 5,
    }
    admin_router._MAIL_INGEST_CANCEL["j1"] = ev
    try:
        r = client.post("/api/v1/admin/mail/ingest/j1/cancel")
    finally:
        admin_router._MAIL_INGEST_JOBS.clear()
        admin_router._MAIL_INGEST_CANCEL.clear()
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"job_id": "j1", "status": "cancelling"}
    assert ev.is_set()


def test_mail_ingest_cancel_not_found(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post("/api/v1/admin/mail/ingest/missing/cancel")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404


def test_mail_ingest_job_status(db) -> None:
    from backend.app.routers import admin as admin_router

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS["abc123"] = {
        "status": "completed",
        "started_at": "t0",
        "completed_at": "t1",
        "lookback_days": 5,
        "stats": {"fetched": 1, "parsed": 0, "unparsed": 0, "skipped": 0, "duplicate": 0},
    }
    try:
        r = client.get("/api/v1/admin/mail/ingest/abc123")
    finally:
        admin_router._MAIL_INGEST_JOBS.pop("abc123", None)
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["job_id"] == "abc123"
    assert r.json()["status"] == "completed"


def test_mail_ingest_cancel_completes_job(db) -> None:
    from backend.app.routers import admin as admin_router

    def slow_ingest(args):
        while not getattr(args, "cancel_event", None).is_set():
            time.sleep(0.01)
        raise IngestCancelled({"fetched": 2, "parsed": 1, "unparsed": 0, "skipped": 0, "duplicate": 0})

    client, app = _client_with_db(db)
    admin_router._MAIL_INGEST_JOBS.clear()
    admin_router._MAIL_INGEST_CANCEL.clear()
    try:
        with patch("backend.app.routers.admin.run_ingest", side_effect=slow_ingest):
            start = client.post("/api/v1/admin/mail/ingest?days=1")
        assert start.status_code == 200
        job_id = start.json()["job_id"]

        cancel = client.post(f"/api/v1/admin/mail/ingest/{job_id}/cancel")
        assert cancel.status_code == 200

        deadline = time.time() + 2.0
        while time.time() < deadline:
            job = client.get(f"/api/v1/admin/mail/ingest/{job_id}").json()
            if job["status"] == "cancelled":
                break
            time.sleep(0.02)
        assert job["status"] == "cancelled"
        assert job["stats"]["fetched"] == 2
    finally:
        admin_router._MAIL_INGEST_JOBS.clear()
        admin_router._MAIL_INGEST_CANCEL.clear()
        app.dependency_overrides.clear()
