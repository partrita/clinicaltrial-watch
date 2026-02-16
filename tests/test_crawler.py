#!/usr/bin/env python3
"""
Tests for crawler.py.
Covers: save_snapshot and fetch_trial_data (mocked).
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crawler import save_snapshot, fetch_trial_data


class TestSaveSnapshot:
    """Tests for save_snapshot."""

    def test_creates_snapshot_file(self, tmp_path):
        data = {"protocolSection": {"statusModule": {"overallStatus": "ACTIVE"}}}
        filepath = save_snapshot("NCT00000001", data, snapshot_dir=str(tmp_path))

        assert os.path.exists(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded == data

    def test_creates_directory_if_missing(self, tmp_path):
        snapshot_dir = str(tmp_path / "new_dir" / "snapshots")
        data = {"key": "value"}
        filepath = save_snapshot("NCT_TEST", data, snapshot_dir=snapshot_dir)

        assert os.path.exists(filepath)

    def test_overwrites_existing_snapshot(self, tmp_path):
        old_data = {"version": 1}
        new_data = {"version": 2}
        save_snapshot("NCT_OW", old_data, snapshot_dir=str(tmp_path))
        save_snapshot("NCT_OW", new_data, snapshot_dir=str(tmp_path))

        filepath = os.path.join(str(tmp_path), "NCT_OW_latest.json")
        with open(filepath, 'r') as f:
            loaded = json.load(f)
        assert loaded == new_data

    def test_unicode_data(self, tmp_path):
        """Should handle Korean and other Unicode correctly."""
        data = {"title": "임상시험 데이터", "status": "모집중"}
        filepath = save_snapshot("NCT_UNICODE", data, snapshot_dir=str(tmp_path))

        with open(filepath, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded["title"] == "임상시험 데이터"


class TestFetchTrialData:
    """Tests for fetch_trial_data (mocked network calls)."""

    @patch('crawler.get_session')
    def test_successful_fetch(self, mock_get_session):
        """Should return parsed JSON on 200 response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"protocolSection": {"statusModule": {}}}

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        import crawler
        original = crawler.HAS_REQUESTS
        crawler.HAS_REQUESTS = True
        try:
            result = fetch_trial_data("NCT00000001")
            assert result is not None
            assert "protocolSection" in result
        finally:
            crawler.HAS_REQUESTS = original

    @patch('crawler.get_session')
    def test_404_returns_none(self, mock_get_session):
        """Should return None for a 404 (trial not found)."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        import crawler
        original = crawler.HAS_REQUESTS
        crawler.HAS_REQUESTS = True
        try:
            result = fetch_trial_data("NCT_NONEXISTENT")
            assert result is None
        finally:
            crawler.HAS_REQUESTS = original

    @patch('crawler.get_session')
    def test_server_error_returns_none(self, mock_get_session):
        """Should return None for server errors (500)."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        import crawler
        original = crawler.HAS_REQUESTS
        crawler.HAS_REQUESTS = True
        try:
            result = fetch_trial_data("NCT_ERROR")
            assert result is None
        finally:
            crawler.HAS_REQUESTS = original

    @patch('crawler.get_session')
    def test_network_exception_returns_none(self, mock_get_session):
        """Should return None on network exception instead of crashing."""
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("Network unreachable")
        mock_get_session.return_value = mock_session

        import crawler
        original = crawler.HAS_REQUESTS
        crawler.HAS_REQUESTS = True
        try:
            result = fetch_trial_data("NCT_TIMEOUT")
            assert result is None
        finally:
            crawler.HAS_REQUESTS = original
