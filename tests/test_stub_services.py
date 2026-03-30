import pytest
from unittest.mock import MagicMock
import argparse

from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.export_service import ExportService, run_export
from backend.app.services.stats_service import StatsService, run_stats

def test_analytics_service_init():
    db = MagicMock()
    service = AnalyticsService(db)
    assert service.db == db

def test_export_service_init():
    db = MagicMock()
    service = ExportService(db)
    assert service.db == db

def test_export_service_run_export():
    args = argparse.Namespace()
    with pytest.raises(NotImplementedError):
        run_export(args)

def test_stats_service_init():
    db = MagicMock()
    service = StatsService(db)
    assert service.db == db

def test_stats_service_run_stats():
    args = argparse.Namespace()
    with pytest.raises(NotImplementedError):
        run_stats(args)
