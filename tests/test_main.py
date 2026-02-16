#!/usr/bin/env python3
"""
Tests for safe_json_load and history-related functions in main.py.
Covers: corrupted JSON, missing files, valid files, and history append logic.
"""

import json
import os
import sys
import tempfile
import shutil
import pytest

# Add src/ to path so we can import modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main import safe_json_load, update_history, update_target_history, flatten_dict, save_target_data


class TestSafeJsonLoad:
    """Tests for the safe_json_load helper."""

    def test_missing_file_returns_default_list(self):
        """When the file does not exist, should return the default value."""
        result = safe_json_load("/nonexistent/path/file.json", default=[])
        assert result == []

    def test_missing_file_returns_custom_default(self):
        result = safe_json_load("/nonexistent/path/file.json", default={"key": "value"})
        assert result == {"key": "value"}

    def test_missing_file_returns_none_default(self):
        result = safe_json_load("/nonexistent/path/file.json", default=None)
        assert result is None

    def test_default_is_empty_list_when_not_specified(self):
        """When default is not provided, it should be []."""
        result = safe_json_load("/nonexistent/path/file.json")
        assert result == []

    def test_valid_json_file(self, tmp_path):
        """Should correctly load a valid JSON file."""
        data = [{"timestamp": "2026-01-01", "diff": "test"}]
        file_path = tmp_path / "valid.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        result = safe_json_load(str(file_path), default=[])
        assert result == data

    def test_valid_json_dict(self, tmp_path):
        """Should correctly load a JSON dict."""
        data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        file_path = tmp_path / "dict.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        result = safe_json_load(str(file_path), default=None)
        assert result == data

    def test_corrupted_json_returns_default(self, tmp_path):
        """When JSON is corrupted (the original bug), should return default instead of crashing."""
        file_path = tmp_path / "corrupted.json"
        # This mimics the exact error from the GitHub Action:
        # trailing comma causing "Expecting property name enclosed in double quotes"
        corrupted_content = '[\n  {\n    "timestamp": "2026-01-01",\n    "event": "test"\n  },\n]'
        file_path.write_text(corrupted_content, encoding="utf-8")
        result = safe_json_load(str(file_path), default=[])
        assert result == []

    def test_empty_file_returns_default(self, tmp_path):
        """An empty file should return default, not crash."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("", encoding="utf-8")
        result = safe_json_load(str(file_path), default=[])
        assert result == []

    def test_invalid_json_syntax_returns_default(self, tmp_path):
        """Totally invalid JSON should return default."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("this is not json at all {{{", encoding="utf-8")
        result = safe_json_load(str(file_path), default=[])
        assert result == []

    def test_truncated_json_returns_default(self, tmp_path):
        """Truncated JSON (e.g. from interrupted write) should return default."""
        file_path = tmp_path / "truncated.json"
        file_path.write_text('[{"timestamp": "2026-01-01"', encoding="utf-8")
        result = safe_json_load(str(file_path), default=[])
        assert result == []

    def test_json_with_single_quotes_returns_default(self, tmp_path):
        """JSON with single quotes (invalid) should return default."""
        file_path = tmp_path / "single_quotes.json"
        file_path.write_text("{'key': 'value'}", encoding="utf-8")
        result = safe_json_load(str(file_path), default={})
        assert result == {}


class TestUpdateHistory:
    """Tests for the update_history function."""

    def test_creates_new_history_file(self, tmp_path):
        """Should create a new history file for a new trial."""
        history_dir = str(tmp_path / "history")
        update_history("NCT00000001", "Initial data collection", history_dir=history_dir)

        history_file = os.path.join(history_dir, "NCT00000001_history.json")
        assert os.path.exists(history_file)

        with open(history_file, 'r') as f:
            history = json.load(f)
        assert len(history) == 1
        assert history[0]["diff"] == "Initial data collection"
        assert "timestamp" in history[0]

    def test_appends_to_existing_history(self, tmp_path):
        """Should append to existing history, not overwrite."""
        history_dir = str(tmp_path / "history")
        update_history("NCT00000002", "First change", history_dir=history_dir)
        update_history("NCT00000002", "Second change", history_dir=history_dir)

        history_file = os.path.join(history_dir, "NCT00000002_history.json")
        with open(history_file, 'r') as f:
            history = json.load(f)
        assert len(history) == 2
        assert history[0]["diff"] == "First change"
        assert history[1]["diff"] == "Second change"

    def test_recovers_from_corrupted_history(self, tmp_path):
        """If existing history file is corrupted, should start fresh instead of crashing."""
        history_dir = str(tmp_path / "history")
        os.makedirs(history_dir)
        history_file = os.path.join(history_dir, "NCT00000003_history.json")

        # Write corrupted JSON
        with open(history_file, 'w') as f:
            f.write('[{"timestamp": "2026-01-01",')

        # This should NOT raise, it should recover gracefully
        update_history("NCT00000003", "New entry after corruption", history_dir=history_dir)

        with open(history_file, 'r') as f:
            history = json.load(f)
        # Corrupted data is lost, but we have the new entry
        assert len(history) == 1
        assert history[0]["diff"] == "New entry after corruption"


class TestUpdateTargetHistory:
    """Tests for the update_target_history function."""

    def test_creates_initial_target_history(self, tmp_path):
        """First call should record initial data collection event."""
        history_dir = str(tmp_path / "history")
        reports = [
            {"id": "NCT001", "name": "Trial 1"},
            {"id": "NCT002", "name": "Trial 2"},
        ]
        update_target_history("TestTarget", reports, history_dir=history_dir)

        history_file = os.path.join(history_dir, "target_testtarget.json")
        assert os.path.exists(history_file)
        with open(history_file, 'r') as f:
            history = json.load(f)
        assert len(history) == 1
        assert "Initial data collection" in history[0]["event"]
        assert "2 trials" in history[0]["event"]

    def test_records_changed_trials(self, tmp_path):
        """Should record which trials changed today."""
        history_dir = str(tmp_path / "history")
        # Create initial history first
        os.makedirs(history_dir)
        history_file = os.path.join(history_dir, "target_testtarget.json")
        with open(history_file, 'w') as f:
            json.dump([{"timestamp": "2026-01-01", "event": "Initial"}], f)

        reports = [
            {"id": "NCT001", "name": "Trial 1", "changed_today": True},
            {"id": "NCT002", "name": "Trial 2"},
        ]
        update_target_history("TestTarget", reports, history_dir=history_dir)

        with open(history_file, 'r') as f:
            history = json.load(f)
        assert len(history) == 2
        assert "NCT001" in history[1]["event"]

    def test_no_update_when_no_changes(self, tmp_path):
        """Should NOT add an entry when there are no changes."""
        history_dir = str(tmp_path / "history")
        os.makedirs(history_dir)
        history_file = os.path.join(history_dir, "target_testtarget.json")
        with open(history_file, 'w') as f:
            json.dump([{"timestamp": "2026-01-01", "event": "Initial"}], f)

        reports = [
            {"id": "NCT001", "name": "Trial 1"},
            {"id": "NCT002", "name": "Trial 2"},
        ]
        update_target_history("TestTarget", reports, history_dir=history_dir)

        with open(history_file, 'r') as f:
            history = json.load(f)
        # Should still be just 1 entry (no changes detected)
        assert len(history) == 1

    def test_recovers_from_corrupted_target_history(self, tmp_path):
        """Corrupted target history should not crash the process."""
        history_dir = str(tmp_path / "history")
        os.makedirs(history_dir)
        history_file = os.path.join(history_dir, "target_testtarget.json")
        with open(history_file, 'w') as f:
            f.write("CORRUPTED DATA {{{")

        reports = [{"id": "NCT001", "name": "Trial 1"}]
        # Should not raise
        update_target_history("TestTarget", reports, history_dir=history_dir)

        with open(history_file, 'r') as f:
            history = json.load(f)
        assert len(history) == 1
        assert "Initial data collection" in history[0]["event"]


class TestFlattenDict:
    """Tests for the flatten_dict utility."""

    def test_simple_flat_dict(self):
        result = flatten_dict({"a": 1, "b": "hello"})
        assert result == {"a": 1, "b": "hello"}

    def test_nested_dict(self):
        result = flatten_dict({"outer": {"inner": "value"}})
        assert result == {"outer_inner": "value"}

    def test_protocol_section_shortening(self):
        """protocolSection should be shortened to Prot and then stripped."""
        result = flatten_dict({"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}})
        # protocolSection -> Prot, stripped prefix -> statusModule -> status (Module stripped)
        assert "status_overallStatus" in result
        assert result["status_overallStatus"] == "ACTIVE"

    def test_list_of_primitives(self):
        result = flatten_dict({"tags": ["a", "b", "c"]})
        assert result["tags"] == "a, b, c"

    def test_list_of_dicts(self):
        result = flatten_dict({"items": [{"id": 1}, {"id": 2}]})
        # Should be JSON string
        assert isinstance(result["items"], str)
        parsed = json.loads(result["items"])
        assert len(parsed) == 2

    def test_empty_dict(self):
        result = flatten_dict({})
        assert result == {}


class TestSaveTargetData:
    """Tests for the save_target_data function."""

    def test_saves_json_and_csv(self, tmp_path, monkeypatch):
        """Should create JSON and CSV files in the target directory."""
        # Change working dir so relative paths resolve within tmp
        monkeypatch.chdir(tmp_path)

        summary = [
            {"id": "NCT001", "name": "Trial 1", "status": "ACTIVE", "monitor_status": "No Change"},
        ]
        raw = [
            {"status_overallStatus": "ACTIVE", "_target": "TestTarget"},
        ]
        save_target_data("TestTarget", summary, raw)

        target_dir = tmp_path / "data" / "targets" / "testtarget"
        assert (target_dir / "status_summary.json").exists()
        assert (target_dir / "status_summary.csv").exists()
        assert (target_dir / "all_trials_raw.csv").exists()

        # Verify JSON content
        with open(target_dir / "status_summary.json", 'r') as f:
            loaded = json.load(f)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "NCT001"

    def test_saves_empty_report(self, tmp_path, monkeypatch):
        """Empty summary should create JSON but skip CSV."""
        monkeypatch.chdir(tmp_path)
        save_target_data("EmptyTarget", [], [])

        target_dir = tmp_path / "data" / "targets" / "emptytarget"
        assert (target_dir / "status_summary.json").exists()
        # CSV should not be created for empty data
        assert not (target_dir / "status_summary.csv").exists()
