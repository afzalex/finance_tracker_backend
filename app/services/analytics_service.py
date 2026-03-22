"""Analytics service — cashflow, category breakdown, top merchants, etc."""

from sqlalchemy.orm import Session


class AnalyticsService:
    """Handles all analytics computations.

    TODO: Implement cashflow aggregation, category breakdown, top merchants,
          recurring transaction detection, and anomaly detection.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
