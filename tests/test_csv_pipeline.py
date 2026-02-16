#!/usr/bin/env python3
"""
Tests for the CSV generation pipeline.
Ensures that save_target_data produces CSV files that can be read by pandas
and contain the columns expected by the Quarto .qmd visualization pages.
"""

import csv
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main import save_target_data, flatten_dict


# Simulated raw trial data from ClinicalTrials.gov API
SAMPLE_RAW_TRIAL = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT00000001",
            "briefTitle": "Test Trial Alpha"
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2025-01-15"},
            "completionDateStruct": {"date": "2026-12-31"}
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Acme Pharma"}
        },
        "designModule": {
            "enrollmentInfo": {"count": 100},
            "phases": ["PHASE2"]
        },
        "conditionsModule": {
            "conditions": ["Melanoma", "Skin Cancer"]
        }
    }
}

SAMPLE_RAW_TRIAL_2 = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT00000002",
            "briefTitle": "Test Trial Beta"
        },
        "statusModule": {
            "overallStatus": "COMPLETED",
            "startDateStruct": {"date": "2024-06-01"},
            "completionDateStruct": {"date": "2025-11-30"}
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "BioGen Labs"}
        },
        "designModule": {
            "enrollmentInfo": {"count": 250},
            "phases": ["PHASE3"]
        },
        "conditionsModule": {
            "conditions": ["Lung Cancer"]
        }
    }
}

# Expected columns that .qmd files reference for plotly charts
QMD_EXPECTED_COLUMNS = [
    "status_overallStatus",                    # Status & Phase chart
    "design_phases",                           # Phase pie chart
    "sponsorCollaborators_leadSponsor_name",   # Top Sponsors chart
]


class TestFlattenDictColumnNames:
    """Verify flatten_dict produces the exact column names .qmd files expect."""

    def test_status_column_name(self):
        flat = flatten_dict(SAMPLE_RAW_TRIAL)
        assert "status_overallStatus" in flat, (
            f"Expected 'status_overallStatus' but got keys: "
            f"{[k for k in flat if 'status' in k.lower()]}"
        )
        assert flat["status_overallStatus"] == "RECRUITING"

    def test_phases_column_name(self):
        flat = flatten_dict(SAMPLE_RAW_TRIAL)
        assert "design_phases" in flat, (
            f"Expected 'design_phases' but got keys: "
            f"{[k for k in flat if 'phase' in k.lower()]}"
        )

    def test_sponsor_column_name(self):
        flat = flatten_dict(SAMPLE_RAW_TRIAL)
        assert "sponsorCollaborators_leadSponsor_name" in flat, (
            f"Expected 'sponsorCollaborators_leadSponsor_name' but got keys: "
            f"{[k for k in flat if 'sponsor' in k.lower()]}"
        )
        assert flat["sponsorCollaborators_leadSponsor_name"] == "Acme Pharma"

    def test_all_qmd_expected_columns_present(self):
        """All columns referenced by .qmd plotly charts must exist."""
        flat = flatten_dict(SAMPLE_RAW_TRIAL)
        for col in QMD_EXPECTED_COLUMNS:
            assert col in flat, (
                f"Column '{col}' required by .qmd charts is missing. "
                f"Available keys: {sorted(flat.keys())}"
            )


class TestSaveTargetDataCSV:
    """Verify save_target_data creates CSV files readable by pandas."""

    def _make_data(self):
        """Generate sample report and raw data."""
        reports = [
            {"id": "NCT00000001", "status": "RECRUITING", "sponsor": "Acme"},
            {"id": "NCT00000002", "status": "COMPLETED", "sponsor": "BioGen"},
        ]
        raw_data = [
            flatten_dict(SAMPLE_RAW_TRIAL),
            flatten_dict(SAMPLE_RAW_TRIAL_2),
        ]
        return reports, raw_data

    def test_csv_files_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        reports, raw_data = self._make_data()

        save_target_data("TestTarget", reports, raw_data)

        target_dir = tmp_path / "data" / "targets" / "testtarget"
        assert (target_dir / "status_summary.csv").exists()
        assert (target_dir / "all_trials_raw.csv").exists()
        assert (target_dir / "status_summary.json").exists()

    def test_csv_readable_by_pandas(self, tmp_path, monkeypatch):
        """CSV must be parseable by pandas without errors."""
        pd = pytest.importorskip("pandas")
        monkeypatch.chdir(tmp_path)
        reports, raw_data = self._make_data()

        save_target_data("TestTarget", reports, raw_data)

        csv_path = str(tmp_path / "data" / "targets" / "testtarget" / "all_trials_raw.csv")
        df = pd.read_csv(csv_path)

        assert len(df) == 2
        assert not df.empty

    def test_csv_contains_qmd_columns(self, tmp_path, monkeypatch):
        """CSV must contain all columns that .qmd charts reference."""
        pd = pytest.importorskip("pandas")
        monkeypatch.chdir(tmp_path)
        reports, raw_data = self._make_data()

        save_target_data("TestTarget", reports, raw_data)

        csv_path = str(tmp_path / "data" / "targets" / "testtarget" / "all_trials_raw.csv")
        df = pd.read_csv(csv_path)

        for col in QMD_EXPECTED_COLUMNS:
            assert col in df.columns, (
                f"Column '{col}' required by .qmd plotly charts is missing from CSV. "
                f"Available columns: {sorted(df.columns.tolist())}"
            )

    def test_csv_status_values_correct(self, tmp_path, monkeypatch):
        """Status column should have correct values for plotly chart."""
        pd = pytest.importorskip("pandas")
        monkeypatch.chdir(tmp_path)
        reports, raw_data = self._make_data()

        save_target_data("TestTarget", reports, raw_data)

        csv_path = str(tmp_path / "data" / "targets" / "testtarget" / "all_trials_raw.csv")
        df = pd.read_csv(csv_path)

        statuses = df["status_overallStatus"].tolist()
        assert "RECRUITING" in statuses
        assert "COMPLETED" in statuses

    def test_csv_sponsor_values_correct(self, tmp_path, monkeypatch):
        """Sponsor column should have correct values for plotly chart."""
        pd = pytest.importorskip("pandas")
        monkeypatch.chdir(tmp_path)
        reports, raw_data = self._make_data()

        save_target_data("TestTarget", reports, raw_data)

        csv_path = str(tmp_path / "data" / "targets" / "testtarget" / "all_trials_raw.csv")
        df = pd.read_csv(csv_path)

        sponsors = df["sponsorCollaborators_leadSponsor_name"].tolist()
        assert "Acme Pharma" in sponsors
        assert "BioGen Labs" in sponsors

    def test_empty_raw_data_no_csv(self, tmp_path, monkeypatch):
        """When no raw data, CSV should not be created but no crash."""
        monkeypatch.chdir(tmp_path)
        reports = [{"id": "NCT1", "status": "OK"}]
        save_target_data("EmptyTarget", reports, [])

        target_dir = tmp_path / "data" / "targets" / "emptytarget"
        assert (target_dir / "status_summary.json").exists()
        assert not (target_dir / "all_trials_raw.csv").exists()


class TestPublishWorkflowDataAvailability:
    """Verify that data generation runs before Quarto render."""

    def test_daily_watch_generates_before_render(self):
        """daily-watch.yml must run main.py BEFORE quarto render."""
        yml_path = os.path.join(
            os.path.dirname(__file__), '..', '.github', 'workflows', 'daily-watch.yml'
        )
        with open(yml_path, 'r') as f:
            content = f.read()

        main_pos = content.find("src/main.py")
        render_pos = content.find("quarto publish")

        assert main_pos != -1, "daily-watch.yml must run main.py"
        assert render_pos != -1, "daily-watch.yml must run quarto"
        assert main_pos < render_pos, (
            "main.py must run BEFORE quarto render in daily-watch.yml"
        )

    def test_publish_generates_before_render(self):
        """publish.yml must run main.py BEFORE quarto render."""
        yml_path = os.path.join(
            os.path.dirname(__file__), '..', '.github', 'workflows', 'publish.yml'
        )
        with open(yml_path, 'r') as f:
            content = f.read()

        main_pos = content.find("src/main.py")
        render_pos = content.find("pixi run render")

        assert main_pos != -1, (
            "publish.yml must run main.py BEFORE render to ensure CSV data exists"
        )
        assert render_pos != -1, "publish.yml must run quarto render"
        assert main_pos < render_pos, (
            "main.py must run BEFORE quarto render in publish.yml"
        )
