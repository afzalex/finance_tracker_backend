"""Stats service — monthly debit/credit/net totals (also called by CLI stats command)."""

import argparse

from sqlalchemy.orm import Session


class StatsService:
    """Computes monthly summary figures.

    TODO: Implement monthly aggregation query.
    """

    def __init__(self, db: Session) -> None:
        self.db = db


def run_stats(args: argparse.Namespace) -> None:
    """CLI entry point for the ``stats`` command.

    TODO: Call StatsService and print results to terminal.
    """
    raise NotImplementedError
