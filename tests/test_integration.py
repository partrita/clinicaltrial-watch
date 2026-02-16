#!/usr/bin/env python3
"""
Integration test for process_trial.
Uses mocking to avoid real network calls while testing the full processing pipeline.
"""

import json
import os
import sys
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main import process_trial


# Sample trial data mimicking real ClinicalTrials.gov API response
SAMPLE_TRIAL_DATA = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT00000001",
            "briefTitle": "Test Trial"
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2025-01-01"},
            "completionDateStruct": {"date": "2026-12-31"},
            "lastUpdatePostDateStruct": {"date": "2026-02-01"},
            "lastUpdateSubmitDate": "2026-01-28"
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Test University"}
        },
        "designModule": {
            "enrollmentInfo": {"count": 100},
            "phases": ["PHASE2"]
        },
        "conditionsModule": {
            "conditions": ["Cancer", "Melanoma"]
        },
        "descriptionModule": {
            "briefSummary": "A test trial for testing.",
            "detailedDescription": "Detailed description of the test trial."
        },
        "outcomesModule": {
            "primaryOutcomes": [
                {"measure": "Overall Survival"}
            ]
        }
    }
}


class TestProcessTrial:
    """Integration tests for process_trial."""

    @patch('main.fetch_trial_data')
    @patch('main.save_snapshot')
    @patch('main.compare_snapshots', return_value=None)
    def test_successful_processing(self, mock_compare, mock_save, mock_fetch, tmp_path, monkeypatch):
        """Should process a trial and return a valid report."""
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = SAMPLE_TRIAL_DATA

        trial = {"id": "NCT00000001", "name": "Test Trial"}
        report, raw = process_trial(trial, "TestTarget")

        assert report is not None
        assert raw is not None
        assert report["id"] == "NCT00000001"
        assert report["sponsor"] == "Test University"
        assert report["status"] == "RECRUITING"
        assert report["conditions"] == "Cancer, Melanoma"
        assert report["phases"] == "PHASE2"
        assert report["enrollment"] == 100
        assert report["primary_outcome"] == "Overall Survival"
        assert report["monitor_status"] == "No Change"

    @patch('main.fetch_trial_data')
    def test_no_data_available(self, mock_fetch, tmp_path, monkeypatch):
        """When API returns None and no local snapshot, should return None, None."""
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = None

        trial = {"id": "NCT_MISSING", "name": "Missing Trial"}
        report, raw = process_trial(trial, "TestTarget")

        assert report is None
        assert raw is None

    @patch('main.fetch_trial_data')
    @patch('main.save_snapshot')
    @patch('main.compare_snapshots', return_value=None)
    def test_fallback_to_local_snapshot(self, mock_compare, mock_save, mock_fetch, tmp_path, monkeypatch):
        """When API fails, should fall back to local snapshot."""
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = None

        # Create a local snapshot
        snapshot_dir = tmp_path / "data" / "snapshots"
        snapshot_dir.mkdir(parents=True)
        snapshot_file = snapshot_dir / "NCT_LOCAL_latest.json"
        snapshot_file.write_text(json.dumps(SAMPLE_TRIAL_DATA), encoding="utf-8")

        trial = {"id": "NCT_LOCAL", "name": "Local Trial"}
        report, raw = process_trial(trial, "TestTarget")

        assert report is not None
        assert report["sponsor"] == "Test University"

    @patch('main.fetch_trial_data')
    @patch('main.save_snapshot')
    @patch('main.compare_snapshots', return_value=None)
    def test_corrupted_local_snapshot(self, mock_compare, mock_save, mock_fetch, tmp_path, monkeypatch):
        """Corrupted local snapshot should not crash, should return None."""
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = None

        # Create a corrupted local snapshot
        snapshot_dir = tmp_path / "data" / "snapshots"
        snapshot_dir.mkdir(parents=True)
        snapshot_file = snapshot_dir / "NCT_BADLOCAL_latest.json"
        snapshot_file.write_text("CORRUPTED {{{", encoding="utf-8")

        trial = {"id": "NCT_BADLOCAL", "name": "Corrupted Local"}
        report, raw = process_trial(trial, "TestTarget")

        assert report is None
        assert raw is None

    @patch('main.fetch_trial_data')
    @patch('main.save_snapshot')
    @patch('main.compare_snapshots')
    def test_with_changes_detected(self, mock_compare, mock_save, mock_fetch, tmp_path, monkeypatch):
        """When changes are detected, report should reflect that."""
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = SAMPLE_TRIAL_DATA

        # Simulate a diff result
        mock_compare.return_value = {
            "Status": {"old": "RECRUITING", "new": "COMPLETED"}
        }

        trial = {"id": "NCT_CHANGED", "name": "Changed Trial"}

        # Need to handle the case where diff_engine doesn't have deepdiff
        import diff_engine
        original = diff_engine.HAS_DEEPDIFF
        diff_engine.HAS_DEEPDIFF = False
        try:
            report, raw = process_trial(trial, "TestTarget")
        finally:
            diff_engine.HAS_DEEPDIFF = original

        assert report is not None
        assert report.get("changed_today") is True
        assert "RECENT CHANGES FOUND" in report["details"]

    @patch('main.fetch_trial_data')
    @patch('main.save_snapshot')
    @patch('main.compare_snapshots', return_value=None)
    def test_missing_optional_fields(self, mock_compare, mock_save, mock_fetch, tmp_path, monkeypatch):
        """Trial data with missing optional fields should not crash."""
        monkeypatch.chdir(tmp_path)
        # Minimal data - missing many optional fields
        minimal_data = {
            "protocolSection": {
                "statusModule": {
                    "overallStatus": "UNKNOWN"
                }
            }
        }
        mock_fetch.return_value = minimal_data

        trial = {"id": "NCT_MINIMAL", "name": "Minimal Trial"}
        report, raw = process_trial(trial, "TestTarget")

        assert report is not None
        assert report["status"] == "UNKNOWN"
        assert report["sponsor"] == "N/A"
        assert report["conditions"] == "N/A"
        assert report["phases"] == "N/A"
        assert report["enrollment"] == "N/A"
        assert report["primary_outcome"] == "N/A"
