#!/usr/bin/env python3
"""
Tests for diff_engine.py.
Covers: compare_snapshots with corrupted files, missing files, identical/changed data.
        format_diff with various diff types.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from diff_engine import compare_snapshots, format_diff


class TestCompareSnapshots:
    """Tests for compare_snapshots."""

    def test_no_previous_snapshot(self, tmp_path):
        """When no previous snapshot exists, should return None (first run)."""
        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        result = compare_snapshots("NCT_NEW", new_data, snapshot_dir=str(tmp_path))
        assert result is None

    def test_identical_data_returns_empty(self, tmp_path):
        """When old and new data are identical, diff should be empty/None."""
        data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        snapshot_path = tmp_path / "NCT_SAME_latest.json"
        snapshot_path.write_text(json.dumps(data), encoding="utf-8")

        result = compare_snapshots("NCT_SAME", data, snapshot_dir=str(tmp_path))
        # DeepDiff returns empty dict {} for no changes, our fallback returns None
        assert not result  # Both {} and None are falsy

    def test_detects_status_change(self, tmp_path):
        """Should detect when overallStatus changes."""
        old_data = {"protocolSection": {"statusModule": {"overallStatus": "RECRUITING"}}}
        new_data = {"protocolSection": {"statusModule": {"overallStatus": "COMPLETED"}}}

        snapshot_path = tmp_path / "NCT_CHANGE_latest.json"
        snapshot_path.write_text(json.dumps(old_data), encoding="utf-8")

        result = compare_snapshots("NCT_CHANGE", new_data, snapshot_dir=str(tmp_path))
        assert result  # Should be non-empty

    def test_detects_new_field(self, tmp_path):
        """Should detect when a new field is added."""
        old_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE", "newField": "value"}}}

        snapshot_path = tmp_path / "NCT_NEWFIELD_latest.json"
        snapshot_path.write_text(json.dumps(old_data), encoding="utf-8")

        result = compare_snapshots("NCT_NEWFIELD", new_data, snapshot_dir=str(tmp_path))
        assert result  # Should detect the new field

    def test_corrupted_previous_snapshot_returns_none(self, tmp_path):
        """Corrupted previous snapshot should return None, not crash."""
        snapshot_path = tmp_path / "NCT_CORRUPT_latest.json"
        snapshot_path.write_text("THIS IS NOT JSON {{{", encoding="utf-8")

        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        result = compare_snapshots("NCT_CORRUPT", new_data, snapshot_dir=str(tmp_path))
        assert result is None

    def test_empty_previous_snapshot_returns_none(self, tmp_path):
        """Empty previous snapshot file should return None, not crash."""
        snapshot_path = tmp_path / "NCT_EMPTY_latest.json"
        snapshot_path.write_text("", encoding="utf-8")

        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        result = compare_snapshots("NCT_EMPTY", new_data, snapshot_dir=str(tmp_path))
        assert result is None

    def test_truncated_json_snapshot_returns_none(self, tmp_path):
        """Truncated JSON (from interrupted write) should return None."""
        snapshot_path = tmp_path / "NCT_TRUNC_latest.json"
        snapshot_path.write_text('{"protocolSection": {"statusModule":', encoding="utf-8")

        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        result = compare_snapshots("NCT_TRUNC", new_data, snapshot_dir=str(tmp_path))
        assert result is None

    def test_missing_protocol_section(self, tmp_path):
        """Old data without protocolSection should not crash."""
        old_data = {"otherSection": {"someField": "value"}}
        new_data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}

        snapshot_path = tmp_path / "NCT_NOPROTO_latest.json"
        snapshot_path.write_text(json.dumps(old_data), encoding="utf-8")

        result = compare_snapshots("NCT_NOPROTO", new_data, snapshot_dir=str(tmp_path))
        assert result  # There are differences (new has protocolSection, old doesn't)


class TestFormatDiff:
    """Tests for format_diff."""

    def test_empty_diff(self):
        assert format_diff(None) == ""
        assert format_diff({}) == ""

    def test_fallback_diff_format(self):
        """Fallback diff (simple dict) should produce readable output."""
        diff = {
            "Status": {"old": "RECRUITING", "new": "COMPLETED"}
        }
        # Use monkeypatch to simulate no deepdiff
        import diff_engine
        original = diff_engine.HAS_DEEPDIFF
        diff_engine.HAS_DEEPDIFF = False
        try:
            result = format_diff(diff)
            assert "RECRUITING" in result
            assert "COMPLETED" in result
        finally:
            diff_engine.HAS_DEEPDIFF = original

    def test_deepdiff_values_changed(self):
        """DeepDiff-style diff with values_changed should format correctly."""
        import diff_engine
        if not diff_engine.HAS_DEEPDIFF:
            pytest.skip("deepdiff not installed")

        from deepdiff import DeepDiff
        old = {"statusModule": {"overallStatus": "RECRUITING"}}
        new = {"statusModule": {"overallStatus": "COMPLETED"}}
        diff = DeepDiff(old, new, ignore_order=True)

        result = format_diff(diff)
        assert "RECRUITING" in result
        assert "COMPLETED" in result

    def test_deepdiff_item_added(self):
        """DeepDiff-style diff with new items should format correctly."""
        import diff_engine
        if not diff_engine.HAS_DEEPDIFF:
            pytest.skip("deepdiff not installed")

        from deepdiff import DeepDiff
        old = {"statusModule": {"overallStatus": "ACTIVE"}}
        new = {"statusModule": {"overallStatus": "ACTIVE", "newField": "data"}}
        diff = DeepDiff(old, new, ignore_order=True)

        result = format_diff(diff)
        assert "added" in result.lower() or "newField" in result
