"""Shared context for post-classification message handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.ingestion.classifier import ClassificationResult
from backend.ingestion.extraction import EmailContent
from backend.ingestion.parsers import TransactionParser


@dataclass
class HandlerContext:
    """Inputs for a single handler after classification."""

    db: Session
    email: EmailContent
    result: ClassificationResult
    parser: TransactionParser
    stats: dict[str, Any]
