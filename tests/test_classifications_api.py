from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.classification import Classification
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.database import get_db
from tests.conftest import seed_classification


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_list_classifications_order_and_shape(db) -> None:
    low = seed_classification(
        db,
        name="Low rule",
        message_type="SINK",
        priority=1,
        sender_match_regex=r"@x",
    )
    high = seed_classification(
        db,
        name="High rule",
        message_type="TRANSACTION_ALERT",
        priority=100,
        sender_match_regex=r"@bank",
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/classifications")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["id"] == high.id
    assert data[0]["name"] == "High rule"
    assert data[0]["message_type"] == "TRANSACTION_ALERT"
    assert data[0]["priority"] == 100
    assert data[0]["sender_match_regex"] == r"@bank"
    assert data[1]["id"] == low.id
    assert data[1]["priority"] == 1
    assert data[0]["mail_count"] == 0
    assert data[1]["mail_count"] == 0


def test_list_classifications_includes_mail_count(db) -> None:
    high = seed_classification(
        db,
        name="High",
        message_type="TRANSACTION_ALERT",
        priority=100,
        sender_match_regex=r"@a",
    )
    low = seed_classification(
        db,
        name="Low",
        message_type="OTHER",
        priority=1,
        sender_match_regex=r"@b",
    )
    for i in range(2):
        fe = FetchedEmail(
            mail_id=f"m{i}",
            internal_date_ms=1,
            body_text="x",
        )
        db.add(fe)
        db.flush()
        db.add(
            FetchedEmailEnrichment(
                fetched_email_id=fe.id,
                classification_id=high.id,
            )
        )
    fe3 = FetchedEmail(mail_id="m3", internal_date_ms=1, body_text="x")
    db.add(fe3)
    db.flush()
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe3.id,
            classification_id=low.id,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/classifications")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data[0]["id"] == high.id
    assert data[0]["mail_count"] == 2
    assert data[1]["id"] == low.id
    assert data[1]["mail_count"] == 1


def test_list_classifications_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/classifications")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []

def test_list_classifications_clamps_priority_0_to_1(db) -> None:
    # Simulate legacy/bad data already present in a real SQLite DB.
    db.add(
        Classification(
            name="Legacy",
            message_type="OTHER",
            priority=0,
            is_active=True,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/classifications")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()[0]["priority"] == 1


def test_patch_classification_updates_and_returns_read(db) -> None:
    row = seed_classification(
        db,
        name="Original",
        message_type="SINK",
        priority=10,
        sender_match_regex=r"@old",
    )
    db.commit()
    before_updated = row.updated_at

    client, app = _client_with_db(db)
    try:
        r = client.patch(
            f"/api/v1/classifications/{row.id}",
            json={
                "name": "Renamed",
                "priority": 99,
                "message_type": "TRANSACTION_ALERT",
                "sender_match_regex": r"@new",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["id"] == row.id
    assert data["name"] == "Renamed"
    assert data["priority"] == 99
    assert data["message_type"] == "TRANSACTION_ALERT"
    assert data["sender_match_regex"] == r"@new"
    db.refresh(row)
    assert row.name == "Renamed"
    assert row.updated_at >= before_updated


def test_patch_classification_empty_body_no_db_write(db) -> None:
    row = seed_classification(db, name="X", message_type="OTHER", priority=1)
    db.commit()
    before = row.updated_at

    client, app = _client_with_db(db)
    try:
        r = client.patch(f"/api/v1/classifications/{row.id}", json={})
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["name"] == "X"
    db.refresh(row)
    assert row.updated_at == before


def test_patch_classification_404(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.patch("/api/v1/classifications/99999", json={"name": "n"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404


def test_patch_classification_invalid_message_type(db) -> None:
    row = seed_classification(db, name="Y", message_type="SINK", priority=1)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.patch(
            f"/api/v1/classifications/{row.id}",
            json={"message_type": "NOT_A_REAL_TYPE"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 422


def test_create_classification(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/classifications",
            json={
                "name": "New rule",
                "message_type": "OTHER",
                "priority": 42,
                "sender_match_regex": r"@new",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "New rule"
    assert data["message_type"] == "OTHER"
    assert data["priority"] == 42
    assert data["is_active"] is True
    assert data["mail_count"] == 0


def test_delete_classification_soft(db) -> None:
    row = seed_classification(db, name="Z", message_type="OTHER", priority=1)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.delete(f"/api/v1/classifications/{row.id}")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    db.refresh(row)
    assert row.is_active is False


def test_delete_classification_idempotent(db) -> None:
    row = seed_classification(db, name="Off", message_type="OTHER", priority=1)
    row.is_active = False
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.delete(f"/api/v1/classifications/{row.id}")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is False
