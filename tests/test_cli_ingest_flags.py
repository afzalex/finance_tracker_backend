"""CLI parsing for ingest run-mode flags."""

import argparse

import pytest

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


def test_ingest_poll_invokes_run_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[argparse.Namespace] = []

    def capture(a: argparse.Namespace) -> None:
        calls.append(a)

    monkeypatch.setattr("backend.ingestion.pipeline.run_poll", capture)
    from backend.ingestion.pipeline import run_ingest

    ns = argparse.Namespace(
        poll=True,
        mail=True,
        unparsed=False,
        offline=False,
        once=None,
        force=None,
    )
    run_ingest(ns)
    assert len(calls) == 1
    assert calls[0] is ns


def test_poll_command_accepts_offline() -> None:
    args = build_parser().parse_args(["poll", "--offline"])
    assert args.command == "poll"
    assert args.offline is True


def test_ingest_args_for_poll_tick_strips_run_modes() -> None:
    from backend.ingestion.pipeline import _ingest_args_for_poll_tick

    base = argparse.Namespace(
        poll=True,
        once=3,
        force=10,
        only_mail_id="mid",
        mail=False,
        unparsed=True,
        offline=False,
    )
    tick = _ingest_args_for_poll_tick(base)
    assert tick.poll is False
    assert tick.once is None
    assert tick.force is None
    assert getattr(tick, "only_mail_id", None) is None
    assert tick.mail is False
    assert tick.unparsed is True
    assert tick.offline is False


def test_ingest_only_mail_id_parses() -> None:
    args = build_parser().parse_args(["ingest", "--only-mail-id", "abc123"])
    assert args.only_mail_id == "abc123"
