"""Historical operational receipts are not application image assets."""
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("filename", ["Containerfile", "Containerfile.combined"])
def test_images_do_not_copy_historical_receipts(filename):
    source = (Path(__file__).resolve().parents[1] / filename).read_text()
    assert not any(line.strip().startswith("COPY receipts/") for line in source.splitlines())


def test_build_context_excludes_historical_receipts():
    ignore = Path(__file__).resolve().parents[1] / ".dockerignore"
    assert "receipts/" in ignore.read_text().splitlines()


@pytest.mark.parametrize("report", [None, {"evaluations": {"total": 1}}])
def test_summit_report_without_packaged_history(monkeypatch, tmp_path, report):
    from api.routers.dashboard import infra
    from collectors.labagator import collect_labagator
    from db import database

    # Empty local path stands in for an image with no historical assets.
    monkeypatch.setattr(infra, "Path", lambda *_: tmp_path)
    monkeypatch.setattr(infra, "_load_latest_babylon", lambda: {})
    session = Mock()
    monkeypatch.setattr(database, "get_db", lambda: iter([session]))
    monkeypatch.setattr(infra.repository, "get_latest_scan_snapshot", lambda *_: report)
    reader = Mock(return_value={})
    monkeypatch.setattr(collect_labagator, "summarize_labs", reader)
    response = infra.dashboard_summit_report()
    assert response["report"] == (report or {})
    assert response["has_data"] is bool(report)
    assert response["live_subjects"] == {}
    assert response["reclamation"] == {}
    session.close.assert_called_once()
    reader.assert_called_once()
