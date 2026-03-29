"""DB-driven message classifier.

Loads classification rules from the ``classifications`` table in priority order
and evaluates each incoming email against them.  The first matching rule wins.

Message types
-------------
TRANSACTION_ALERT  → sent to parser system.
INVESTMENT_NOTICE  → sent to parser system.
STATEMENT          → stored in unparsed queue (later phase).
SINK               → silently discarded.
OTHER              → catch-all; stored in unparsed queue.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.classification import Classification
from backend.ingestion.utils import match_regex, merge_extract_groups

logger = logging.getLogger(__name__)

# Stored in ``fetched_email_enrichments.classification_reason`` when no rule matches.
CLASSIFICATION_NO_MATCH_REASON = "no_classification_rule_matched"


@dataclass
class ClassificationResult:
    """Outcome of classifying a single email.

    Attributes:
        message_type:            One of the ``MessageType`` enum values as a string.
        classification_id:       PK of the matching ``Classification`` row, or ``None``
                                 when the fallback OTHER rule applies.
        classification_reason:   Matching rule name, or ``CLASSIFICATION_NO_MATCH_REASON`` when
                                 no rule matched; stored in enrichment.
        extracted:               Named groups pulled by the rule's extract regexes
                                 (may be empty when no extract regex is configured).
    """

    message_type: str
    classification_id: Optional[int]
    classification_reason: Optional[str] = None
    extracted: dict = field(default_factory=dict)


class MessageClassifier:
    """Classifies an email against DB-stored rules."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._rules: list[Classification] = []

    def load_rules(self) -> None:
        """Load active classification rules from DB in descending priority order."""
        self._rules = (
            self.db.query(Classification)
            .filter(Classification.is_active.is_(True))
            .order_by(Classification.priority.desc())
            .all()
        )
        logger.debug("Loaded %d classification rules", len(self._rules))

    def classify(self, sender: str, subject: str, body: str, snippet: str = "") -> ClassificationResult:
        """Evaluate rules against an email and return the first match.

        Falls back to OTHER/no_match if no rule fires.
        """
        sender = sender or ""
        subject = subject or ""
        body = body or ""
        snippet = snippet or ""

        for rule in self._rules:
            results = tuple(
                match_regex(pattern, text, empty_means_match=False)
                for pattern, text in (
                    (rule.sender_match_regex, sender),
                    (rule.subject_match_regex, subject),
                    (rule.body_match_regex, body),
                )
            )
            # Skip if any pattern explicitly failed
            if any(r is False for r in results):
                continue

            message_type = rule.message_type.value
            extracted: dict = {}

            # Run optional extract regexes to pull named groups
            body_re = (rule.body_extract_regex or "").strip()
            subject_re = (rule.subject_extract_regex or "").strip()
            snippet_re = (rule.snippet_extract_regex or "").strip()

            if body_re or subject_re or snippet_re:
                body_m = re.search(body_re, body, re.IGNORECASE | re.DOTALL) if body_re else None
                subject_m = re.search(subject_re, subject, re.IGNORECASE | re.DOTALL) if subject_re else None
                snippet_m = re.search(snippet_re, snippet, re.IGNORECASE | re.DOTALL) if snippet_re else None
                extracted = merge_extract_groups(body_m, subject_m, snippet_m)

            logger.debug(
                "Classified as %s (rule=%r id=%d)",
                message_type, rule.name, rule.id,
            )
            return ClassificationResult(
                message_type=message_type,
                classification_id=rule.id,
                classification_reason=rule.name,
                extracted=extracted,
            )

        # No rule matched — DB should have a catch-all OTHER row
        logger.debug("No classification rule matched; defaulting to OTHER")
        return ClassificationResult(
            message_type="OTHER",
            classification_id=None,
            classification_reason=CLASSIFICATION_NO_MATCH_REASON,
        )
