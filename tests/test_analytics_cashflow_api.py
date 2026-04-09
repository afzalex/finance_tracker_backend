from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.transaction import Direction, Origin, Transaction
from backend.database import get_db


def _client_with_db(db):
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def test_cashflow_empty(db) -> None:
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/cashflow?from=2026-01-01&to=2026-12-31")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


def test_cashflow_by_month_credit_debit_total_count(db) -> None:
    db.add(
        Transaction(
            mail_id="a",
            transacted_at=datetime(2026, 2, 10, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="100",
            amount_parsed=100.0,
            currency="INR",
            direction=Direction.CREDIT,
            provider="P",
            merchant="M",
        )
    )
    db.add(
        Transaction(
            mail_id="b",
            transacted_at=datetime(2026, 2, 15, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="40",
            amount_parsed=40.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            merchant="M",
        )
    )
    db.add(
        Transaction(
            mail_id="c",
            transacted_at=datetime(2026, 3, 1, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="10",
            amount_parsed=10.0,
            currency="INR",
            direction=Direction.DEBIT,
            provider="P",
            merchant="M",
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/cashflow?from=2026-01-01&to=2026-12-31")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert rows[0] == {
        "month": "2026-02",
        "credit": 100.0,
        "debit": 40.0,
        "total": 60.0,
        "count": 2,
    }
    assert rows[1] == {
        "month": "2026-03",
        "credit": 0.0,
        "debit": 10.0,
        "total": -10.0,
        "count": 1,
    }


def test_cashflow_respects_date_range(db) -> None:
    db.add(
        Transaction(
            mail_id="x",
            transacted_at=datetime(2026, 1, 31, 23, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="1",
            amount_parsed=1.0,
            currency="INR",
            direction=Direction.CREDIT,
        )
    )
    db.add(
        Transaction(
            mail_id="y",
            transacted_at=datetime(2026, 2, 1, 1, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="2",
            amount_parsed=2.0,
            currency="INR",
            direction=Direction.CREDIT,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/cashflow?from=2026-02-01&to=2026-02-28")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == [
        {"month": "2026-02", "credit": 2.0, "debit": 0.0, "total": 2.0, "count": 1},
    ]


def test_twelve_month_window_start() -> None:
    from backend.app.routers.analytics import _twelve_month_window_start

    assert _twelve_month_window_start(date(2026, 4, 15)) == date(2025, 5, 1)


def test_cashflow_no_query_params_uses_default_range(db) -> None:
    """Default window is last 12 months through today; response is a list (shape only)."""
    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/cashflow")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_cashflow_ignores_excluded(db) -> None:
    db.add(
        Transaction(
            mail_id="included",
            transacted_at=datetime(2026, 1, 10, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="100",
            amount_parsed=100.0,
            currency="INR",
            direction=Direction.DEBIT,
        )
    )
    db.add(
        Transaction(
            mail_id="excluded",
            transacted_at=datetime(2026, 1, 15, 12, 0, 0),
            origin=Origin.EMAIL_ALERT,
            amount="50",
            amount_parsed=50.0,
            currency="INR",
            direction=Direction.DEBIT,
            is_excluded=True,
        )
    )
    db.commit()

    client, app = _client_with_db(db)
    try:
        r = client.get("/api/v1/analytics/cashflow?from=2026-01-01&to=2026-01-31")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["debit"] == 100.0
    assert rows[0]["count"] == 1
