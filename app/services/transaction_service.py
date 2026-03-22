"""Transaction service — query logic for the /transactions endpoint."""

from sqlalchemy.orm import Session


class TransactionService:
    """Handles all transaction retrieval queries.

    TODO: Implement filtering, searching, sorting, deduplication helpers.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
