"""Export service — write transactions to CSV (called by CLI export command)."""

import argparse

from sqlalchemy.orm import Session


class ExportService:
    """Handles CSV export of transactions for a date range.

    TODO: Implement date-range query and CSV writer.
    """

    def __init__(self, db: Session) -> None:
        self.db = db


def run_export(args: argparse.Namespace) -> None:
    """CLI entry point for the ``export`` command.

    TODO: Call ExportService and write CSV to args.out.
    """
    raise NotImplementedError
