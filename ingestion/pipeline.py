"""Ingestion pipeline — orchestrates fetch → classify → parse → save.

Entry points
------------
run_ingest(args)   One-shot or --once / --force run.
run_poll()         Continuous polling daemon.
run_unparsed(args) Re-process messages from the unparsed queue.
"""

import argparse
import time

from backend.config import settings


def run_ingest(args: argparse.Namespace) -> None:
    """Main ingest pipeline.

    Depending on args selects the right source (mail / unparsed / offline)
    and run mode (default cursor / --once / --force).

    TODO: Implement fetch → classify → parse → save → cursor update.
    """
    raise NotImplementedError


def run_poll() -> None:
    """Continuous polling daemon.

    Calls run_ingest in a loop with POLL_SECONDS interval between runs.

    TODO: Wrap run_ingest with sleep loop and graceful SIGTERM handling.
    """
    print(f"Starting poll mode — interval: {settings.poll_seconds}s")
    while True:
        try:
            _args = argparse.Namespace(once=None, poll=True, force=False, mail=True,
                                       unparsed=False, offline=False)
            run_ingest(_args)
        except NotImplementedError:
            pass  # placeholder until implemented
        time.sleep(settings.poll_seconds)


def run_unparsed(args: argparse.Namespace) -> None:
    """List or inspect messages from the unparsed queue.

    TODO: Implement list / show actions.
    """
    raise NotImplementedError
