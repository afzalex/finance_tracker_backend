"""Finance Tracker CLI entry point.

Commands
--------
ingest      Fetch new emails, classify, parse, write to ledger.
poll        Run ingest continuously on POLL_SECONDS interval.
export      Export transactions to CSV.
stats       Print monthly debit/credit/net summary.
unparsed    List / inspect messages that failed to parse.

Run modes for ingest, export, stats, unparsed
---------------------------------------------
(none)      One run from stored cursor (default).
--once N    Fetch only N most recent messages; cursor NOT updated.
--force     Force-fetch last 30 days, ignoring stored cursor.

Source flags (mutually exclusive; not applicable to --poll)
-----------------------------------------------------------
--mail      (default) Fetch from Gmail.
--unparsed  Re-process unparsed queue.
--offline   Re-process from stored fetched_emails.
"""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finance-tracker",
        description="Finance Tracker CLI — ingestion and reporting tool.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── ingest ────────────────────────────────────────────────────────────────
    ingest_p = sub.add_parser("ingest", help="Fetch and store transactions from Gmail.")
    _add_run_mode_flags(ingest_p)
    _add_source_flags(ingest_p)

    # ── poll ──────────────────────────────────────────────────────────────────
    sub.add_parser("poll", help="Run ingest continuously (daemon mode).")

    # ── export ────────────────────────────────────────────────────────────────
    export_p = sub.add_parser("export", help="Export transactions to a CSV file.")
    export_p.add_argument("--from", dest="date_from", required=True, help="Start date (YYYY-MM-DD).")
    export_p.add_argument("--to", dest="date_to", required=True, help="End date (YYYY-MM-DD).")
    export_p.add_argument("--out", default="export.csv", help="Output file path.")

    # ── stats ─────────────────────────────────────────────────────────────────
    stats_p = sub.add_parser("stats", help="Print monthly debit/credit/net totals.")
    stats_p.add_argument("--month", help="Month in YYYY-MM format (default: current month).")

    # ── unparsed ──────────────────────────────────────────────────────────────
    unparsed_p = sub.add_parser("unparsed", help="Inspect messages that failed to parse.")
    unparsed_p.add_argument("--list", action="store_true", help="List all unparsed messages.")
    unparsed_p.add_argument("--show", type=str, metavar="MSG_ID", help="Show a specific message.")

    return parser


def _add_run_mode_flags(p: argparse.ArgumentParser) -> None:
    """Add mutually exclusive run-mode flags to a sub-command parser."""
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", type=int, nargs="?", const=1, metavar="N",
                      help="Fetch N most recent messages (default 1); cursor not updated.")
    mode.add_argument("--poll", action="store_true",
                      help="Run continuously. Source flags do not apply.")
    mode.add_argument("--force", action="store_true",
                      help="Force-fetch last 30 days ignoring stored cursor.")


def _add_source_flags(p: argparse.ArgumentParser) -> None:
    """Add mutually exclusive source flags to a sub-command parser."""
    src = p.add_mutually_exclusive_group()
    src.add_argument("--mail", action="store_true", default=True,
                     help="(default) Fetch from Gmail.")
    src.add_argument("--unparsed", action="store_true",
                     help="Re-process the unparsed queue.")
    src.add_argument("--offline", action="store_true",
                     help="Re-process from stored fetched_emails.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest":
        from backend.ingestion.pipeline import run_ingest  # noqa: PLC0415
        run_ingest(args)
    elif args.command == "poll":
        from backend.ingestion.pipeline import run_poll  # noqa: PLC0415
        run_poll()
    elif args.command == "export":
        from backend.app.services.export_service import run_export  # noqa: PLC0415
        run_export(args)
    elif args.command == "stats":
        from backend.app.services.stats_service import run_stats  # noqa: PLC0415
        run_stats(args)
    elif args.command == "unparsed":
        from backend.ingestion.pipeline import run_unparsed  # noqa: PLC0415
        run_unparsed(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
