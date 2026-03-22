"""DB-driven transaction parsers.

Parsers are defined entirely in the database (``parsers`` table).
Adding support for a new bank/notification format requires only inserting a row
— no code changes.

Mandatory extracted fields (if any missing → message goes to unparsed queue):
  amount      Numeric transaction amount.
  direction   DEBIT or CREDIT.
  provider    Bank or app name (e.g. HDFC, PhonePe).
  account_id  Account/card identifier (e.g. masked last 4 digits).
"""

from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Result of attempting to parse a transaction from an email."""
    success: bool
    fields: dict = field(default_factory=dict)
    parser_id: int | None = None
    failure_reason: str | None = None


class TransactionParser:
    """Attempts to parse transaction fields from a classified email.

    Implements the DB-driven parser system: loads ``parsers`` table rows,
    matches each email against parser rules, and extracts named groups.
    Named-group captures take precedence over per-row defaults.

    TODO: Implement parser loading, matching, extraction, and validation.
    """

    def __init__(self, db_session) -> None:
        self.db = db_session
        self._parsers: list = []

    def load_parsers(self) -> None:
        """Load active parser rows from the DB.

        TODO: Query parsers table.
        """
        raise NotImplementedError

    def parse(self, sender: str, subject: str, body: str, message_type: str) -> ParseResult:
        """Try each loaded parser against the email; return first successful match.

        TODO: Implement match → extract → validate pipeline.
        """
        raise NotImplementedError
