import sys
import argparse
import pytest
from unittest.mock import patch

from backend.cli import main

def test_main_auth(monkeypatch):
    with patch("sys.argv", ["finance-tracker", "auth"]), \
         patch("backend.ingestion.gmail.auth.run_oauth_flow") as mock_run:
        main()
        mock_run.assert_called_once()

def test_main_auth_error(monkeypatch):
    from backend.ingestion.gmail.auth import GmailAuthError
    with patch("sys.argv", ["finance-tracker", "auth"]), \
         patch("backend.ingestion.gmail.auth.run_oauth_flow", side_effect=GmailAuthError("err")), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1

def test_main_ingest():
    with patch("sys.argv", ["finance-tracker", "ingest"]), \
         patch("backend.ingestion.pipeline.run_ingest") as mock_run:
        main()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0].command == "ingest"

def test_main_poll():
    with patch("sys.argv", ["finance-tracker", "poll"]), \
         patch("backend.ingestion.pipeline.run_poll") as mock_run:
        main()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0].command == "poll"

def test_main_export():
    with patch("sys.argv", ["finance-tracker", "export", "--from", "2024-01-01", "--to", "2024-01-31"]), \
         patch("backend.app.services.export_service.run_export") as mock_run:
        main()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0].command == "export"

def test_main_stats():
    with patch("sys.argv", ["finance-tracker", "stats"]), \
         patch("backend.app.services.stats_service.run_stats") as mock_run:
        main()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0].command == "stats"

def test_main_unparsed():
    with patch("sys.argv", ["finance-tracker", "unparsed", "--list"]), \
         patch("backend.ingestion.pipeline.run_unparsed") as mock_run:
        main()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0].command == "unparsed"

def test_main_invalid_command():
    with patch("sys.argv", ["finance-tracker", "invalid_command"]), \
         pytest.raises(SystemExit) as exc:
        main()
    # parse_args should exit if command is not recognized
    assert exc.value.code != 0
