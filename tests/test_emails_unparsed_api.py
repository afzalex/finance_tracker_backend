from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.unparsed_message import UnparsedMessage
from backend.database import get_db
from tests.conftest import seed_classification, seed_parser


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_list_unparsed_emails_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


def test_list_unparsed_emails_joins_mail_id_and_names(db) -> None:
    fe = FetchedEmail(
        mail_id="gmail-unparsed-1",
        subject="Hello",
        snippet="prev",
        internal_date_ms=0,
        body_text="body",
    )
    db.add(fe)
    db.flush()
    cl = seed_classification(db, name="Rule A", sender_match_regex=r"x")
    pr = seed_parser(db, name="Parser B", sender_match_regex=r"y")
    db.add(
        UnparsedMessage(
            fetched_email_id=fe.id,
            reason="no_match",
            classification_id=cl.id,
            parser_id=pr.id,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    row = data[0]
    assert row["mail_id"] == "gmail-unparsed-1"
    assert row["fetched_email_id"] == fe.id
    assert row["subject"] == "Hello"
    assert row["snippet"] == "prev"
    assert row["reason"] == "no_match"
    assert row["classification_name"] == "Rule A"
    assert row["parser_name"] == "Parser B"


def test_unparsed_route_not_shadowed_by_mail_id_path(db) -> None:
    """``/emails/unparsed`` must not be handled as ``mail_id='unparsed'``."""
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []
