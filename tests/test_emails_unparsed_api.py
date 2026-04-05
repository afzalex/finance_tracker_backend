from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.app.models.unparsed_message import UnparsedMessage
from backend.database import get_db
from tests.conftest import seed_classification, seed_parser


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def _parse_api_datetime(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_list_unparsed_emails_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


def test_list_unparsed_emails_joins_mail_id_and_names(db) -> None:
    internal_ms = 1_704_067_200_000
    fe = FetchedEmail(
        mail_id="gmail-unparsed-1",
        subject="Hello",
        snippet="prev",
        internal_date_ms=internal_ms,
        body_text="body",
    )
    db.add(fe)
    db.flush()
    cl = seed_classification(db, name="Rule A", sender_match_regex=r"x")
    pr = seed_parser(db, name="Parser B", sender_match_regex=r"y")
    db.add(
        FetchedEmailEnrichment(
            fetched_email_id=fe.id,
            classification_reason="matched sender pattern",
        )
    )
    um = UnparsedMessage(
        fetched_email_id=fe.id,
        reason="no_match",
        classification_id=cl.id,
        parser_id=pr.id,
    )
    db.add(um)
    db.commit()
    um_id = um.id

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
    assert "snippet" not in row
    expected_at = datetime.fromtimestamp(internal_ms / 1000.0, tz=timezone.utc)
    assert _parse_api_datetime(row["mail_received_at"]) == expected_at
    assert row["reason"] == "no_match"
    assert row["classification_name"] == "Rule A"
    assert row["parser_name"] == "Parser B"
    assert row["classification_reason"] == "matched sender pattern"

    client2, app2 = _client_with_db(db)
    try:
        d = client2.get(f"/api/v1/emails/unparsed/{um_id}")
    finally:
        app2.dependency_overrides.clear()
    assert d.status_code == 200
    payload = d.json()
    assert payload["id"] == um_id
    assert payload["email"]["mail_id"] == "gmail-unparsed-1"
    assert payload["email"]["body_text"] == "body"
    assert payload["enrichment"]["classification_reason"] == "matched sender pattern"


def test_list_unparsed_emails_filter_from_to(db) -> None:
    def ms(y: int, m: int, d: int) -> int:
        return int(datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

    fe_out = FetchedEmail(
        mail_id="jan",
        subject="Jan",
        internal_date_ms=ms(2024, 1, 5),
        body_text="b",
    )
    db.add(fe_out)
    db.flush()
    db.add(UnparsedMessage(fetched_email_id=fe_out.id, reason="r"))
    fe_in = FetchedEmail(
        mail_id="feb",
        subject="Feb",
        internal_date_ms=ms(2024, 2, 14),
        body_text="b",
    )
    db.add(fe_in)
    db.flush()
    db.add(UnparsedMessage(fetched_email_id=fe_in.id, reason="r"))
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed?from=2024-02-01&to=2024-02-29")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["mail_id"] == "feb"


def test_list_unparsed_emails_null_mail_received_at_and_classification_reason(db) -> None:
    fe = FetchedEmail(
        mail_id="gmail-edge",
        subject="S",
        internal_date_ms=0,
        body_text="b",
    )
    db.add(fe)
    db.flush()
    db.add(UnparsedMessage(fetched_email_id=fe.id, reason="r"))
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    row = r.json()[0]
    assert row["mail_received_at"] is None
    assert row["classification_reason"] is None


def test_get_unparsed_email_detail_not_found(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed/99999")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404


def test_unparsed_route_not_shadowed_by_mail_id_path(db) -> None:
    """``/emails/unparsed`` must not be handled as ``mail_id='unparsed'``."""
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/emails/unparsed")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []
