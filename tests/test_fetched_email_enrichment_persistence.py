"""SQLite + ORM: ``FetchedEmailEnrichment`` must insert ``created_at`` / ``updated_at`` without DB defaults.

Regression: ``server_default`` alone does not populate columns on SQLite INSERT; ``insert_default``
must be set on the model so ``get_or_create_fetched_email_enrichment`` / ingest do not fail with
``NOT NULL constraint failed: fetched_email_enrichments.created_at``.
"""

from __future__ import annotations

from backend.app.models.fetched_email import FetchedEmail
from backend.app.models.fetched_email_enrichment import FetchedEmailEnrichment
from backend.ingestion.persistence import (
    get_or_create_fetched_email_enrichment,
    reset_fetched_email_enrichment,
)


def _seed_fetched_email(db) -> FetchedEmail:
    fe = FetchedEmail(
        mail_id="m-sqlite-enrichment-test",
        internal_date_ms=0,
        body_text="x",
    )
    db.add(fe)
    db.flush()
    return fe


def test_sqlite_insert_enrichment_without_explicit_timestamps_succeeds(db) -> None:
    """ORM insert must send timestamps; SQLite has no usable server default for this DDL."""
    fe = _seed_fetched_email(db)
    row = FetchedEmailEnrichment(fetched_email_id=fe.id)
    db.add(row)
    db.commit()

    loaded = db.get(FetchedEmailEnrichment, fe.id)
    assert loaded is not None
    assert loaded.created_at is not None
    assert loaded.updated_at is not None


def test_get_or_create_fetched_email_enrichment_sets_timestamps(db) -> None:
    fe = _seed_fetched_email(db)
    row = get_or_create_fetched_email_enrichment(db, fe.id)
    db.commit()

    assert row.created_at is not None
    assert row.updated_at is not None
    reloaded = db.get(FetchedEmailEnrichment, fe.id)
    assert reloaded is not None
    assert reloaded.created_at == row.created_at
    assert reloaded.updated_at == row.updated_at


def test_get_or_create_returns_existing_row(db) -> None:
    fe = _seed_fetched_email(db)
    first = get_or_create_fetched_email_enrichment(db, fe.id)
    db.commit()
    created = first.created_at

    second = get_or_create_fetched_email_enrichment(db, fe.id)
    assert second is first
    assert second.created_at == created


def test_reset_fetched_email_enrichment_inserts_then_clears_fields(db) -> None:
    """Matches ingest path: ``reset_fetched_email_enrichment`` after raw email insert."""
    fe = _seed_fetched_email(db)
    reset_fetched_email_enrichment(db, fe.id)
    db.commit()

    row = db.get(FetchedEmailEnrichment, fe.id)
    assert row is not None
    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.classification_id is None
    assert row.classification is None
    assert row.classification_reason is None
    assert row.parser_id is None
    assert row.processing_time_ms is None


def test_reset_fetched_email_enrichment_clears_processing_time_ms(db) -> None:
    fe = _seed_fetched_email(db)
    reset_fetched_email_enrichment(db, fe.id)
    row = get_or_create_fetched_email_enrichment(db, fe.id)
    row.processing_time_ms = 99
    db.commit()
    reset_fetched_email_enrichment(db, fe.id)
    db.commit()
    again = db.get(FetchedEmailEnrichment, fe.id)
    assert again is not None
    assert again.processing_time_ms is None
