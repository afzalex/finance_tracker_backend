from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.parser import Parser
from backend.database import get_db
from tests.conftest import seed_parser


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_list_parsers_order_and_shape(db) -> None:
    low = seed_parser(db, name="Low parser", label="L1", priority=1, sender_match_regex=r"@a")
    high = seed_parser(db, name="High parser", label="H1", priority=50, sender_match_regex=r"@b")
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/parsers")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["id"] == high.id
    assert data[0]["name"] == "High parser"
    assert data[0]["label"] == "H1"
    assert data[0]["priority"] == 50
    assert data[1]["id"] == low.id
    assert data[1]["priority"] == 1
    assert data[0]["mail_count"] == 0
    assert data[1]["mail_count"] == 0


def test_list_parsers_includes_mail_count(db) -> None:
    high = seed_parser(db, name="High parser", label="H", priority=50, sender_match_regex=r"@a")
    low = seed_parser(db, name="Low parser", label="L", priority=1, sender_match_regex=r"@b")
    for i in range(2):
        fe = FetchedEmail(
            mail_id=f"p{i}",
            internal_date_ms=1,
            body_text="x",
        )
        db.add(fe)
        db.flush()
        db.add(
            FetchedEmailEnrichment(
                fetched_email_id=fe.id,
                parser_id=high.id,
            )
        )
    fe3 = FetchedEmail(mail_id="p3", internal_date_ms=1, body_text="x")
    db.add(fe3)
    db.flush()
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe3.id,
            parser_id=low.id,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/parsers")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data[0]["id"] == high.id
    assert data[0]["mail_count"] == 2
    assert data[1]["id"] == low.id
    assert data[1]["mail_count"] == 1


def test_list_parsers_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/parsers")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []

def test_list_parsers_clamps_priority_0_to_1(db) -> None:
    db.add(
        Parser(
            name="Legacy",
            label="LEG",
            priority=0,
            is_active=True,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/parsers")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()[0]["priority"] == 1


def test_create_parser(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.post(
            "/api/v1/parsers",
            json={
                "name": "Bank parser",
                "label": "BANK",
                "priority": 20,
                "sender_match_regex": r"@bank",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Bank parser"
    assert data["label"] == "BANK"
    assert data["priority"] == 20
    assert data["is_active"] is True
    assert data["mail_count"] == 0


def test_patch_parser(db) -> None:
    row = seed_parser(db, name="Old", label="O", priority=1)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.patch(
            f"/api/v1/parsers/{row.id}",
            json={"name": "New", "priority": 99},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["priority"] == 99
    assert r.json()["label"] == "O"


def test_delete_parser_soft(db) -> None:
    row = seed_parser(db, name="P", label="L", priority=1)
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.delete(f"/api/v1/parsers/{row.id}")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    db.refresh(row)
    assert row.is_active is False


def test_delete_parser_404(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.delete("/api/v1/parsers/99999")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404
