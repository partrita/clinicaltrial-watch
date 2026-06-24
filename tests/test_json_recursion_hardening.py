import pytest
import os
from unittest.mock import patch, MagicMock
from src.crawler import fetch_trial_data
from src.auto_discover_trials import search_trials
from src.main import safe_json_load


def test_fetch_trial_data_recursion_error():
    """Verify that fetch_trial_data handles RecursionError during JSON parsing."""
    # Create deeply nested JSON that triggers RecursionError
    deep_json = "[" * 20000 + "]" * 20000

    with patch("src.crawler.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.url = "https://clinicaltrials.gov/api/v2/studies/NCT12345678"
        mock_response.iter_content.return_value = [deep_json.encode("utf-8")]
        mock_session.get.return_value = mock_response
        mock_response.__enter__.return_value = mock_response

        # Should return None and not crash
        assert fetch_trial_data("NCT12345678") is None


def test_search_trials_recursion_error():
    """Verify that search_trials handles RecursionError during JSON parsing."""
    deep_json = "[" * 20000 + "]" * 20000

    with patch("src.auto_discover_trials.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.url = "https://clinicaltrials.gov/api/v2/studies"
        mock_response.iter_content.return_value = [deep_json.encode("utf-8")]
        mock_session.get.return_value = mock_response
        mock_response.__enter__.return_value = mock_response

        # Should return [] and not crash
        assert search_trials("Target") == []


def test_safe_json_load_recursion_error():
    """Verify that safe_json_load handles RecursionError during JSON parsing."""
    test_file = "tests/tmp_recursion.json"
    with open(test_file, "w") as f:
        f.write("{}")

    try:
        with patch("json.load", side_effect=RecursionError):
            with pytest.raises(RecursionError):
                safe_json_load(test_file)
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
