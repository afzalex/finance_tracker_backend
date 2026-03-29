"""CLI parsing for ingest run-mode flags."""

from backend.cli import build_parser


def test_ingest_force_no_value_means_unlimited_lookback() -> None:
    args = build_parser().parse_args(["ingest", "--force"])
    assert args.force == -1


def test_ingest_force_with_cap() -> None:
    args = build_parser().parse_args(["ingest", "--force", "100"])
    assert args.force == 100


def test_ingest_default_no_force() -> None:
    args = build_parser().parse_args(["ingest"])
    assert args.force is None
