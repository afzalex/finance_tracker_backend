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

from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class ClassificationResult:
    message_type: str
    classification_id: int
    extracted: dict  # named groups captured by extract_regex


class MessageClassifier:
    """Classifies an email against DB-stored rules.

    TODO: Implement rule loading and regex match evaluation in priority order.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._rules: list = []

    def load_rules(self) -> None:
        """Load active classification rules from DB in descending priority order.

        TODO: Query classifications table.
        """
        raise NotImplementedError

    def classify(self, sender: str, subject: str, body: str) -> ClassificationResult:
        """Evaluate rules against an email and return the first match.

        TODO: Implement regex evaluation loop.
        """
        raise NotImplementedError
