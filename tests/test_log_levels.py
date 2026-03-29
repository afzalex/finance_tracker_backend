import logging

from backend.log_levels import (
    TRACE,
    parse_log_level,
    sqlalchemy_echo_from_log_level,
)


def test_parse_log_level_trace() -> None:
    assert parse_log_level("trace") == TRACE


def test_parse_log_level_debug() -> None:
    assert parse_log_level("debug") == logging.DEBUG


def test_sqlalchemy_echo_only_for_trace() -> None:
    assert sqlalchemy_echo_from_log_level("TRACE") is True
    assert sqlalchemy_echo_from_log_level("DEBUG") is False
    assert sqlalchemy_echo_from_log_level("INFO") is False
