import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import process_trial
from auto_discover_trials import extract_trials
from unittest.mock import patch


def test_process_trial_malformed_api_data():
    """Verify that process_trial handles None values for expected dictionary fields."""
    trial = {"id": "NCT12345678", "name": "Test Trial"}

    # Test case 1: protocolSection is None
    mock_data_1 = {"protocolSection": None}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_1),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["sponsor"] == "N/A"
        assert report["status"] == "N/A"

    # Test case 2: statusModule is None
    mock_data_2 = {"protocolSection": {"statusModule": None}}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_2),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["study_start"] == "N/A"
        assert report["status"] == "N/A"

    # Test case 3: sponsorCollaboratorsModule is None
    mock_data_3 = {"protocolSection": {"sponsorCollaboratorsModule": None}}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_3),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["sponsor"] == "N/A"

    # Test case 4: designModule is None
    mock_data_4 = {"protocolSection": {"designModule": None}}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_4),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["enrollment"] == "N/A"
        assert report["phases"] == "N/A"

    # Test case 5: outcomesModule is None
    mock_data_5 = {"protocolSection": {"outcomesModule": None}}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_5),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["primary_outcome"] == "N/A"

    # Test case 6: descriptionModule is None
    mock_data_6 = {"protocolSection": {"descriptionModule": None}}
    with (
        patch("main.fetch_trial_data", return_value=mock_data_6),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["details"] == "N/A"


def test_extract_trials_malformed_api_data():
    """Verify that extract_trials handles None values for expected dictionary fields."""
    # Test case 1: protocolSection is None
    api_studies_1 = [{"protocolSection": None}]
    assert extract_trials(api_studies_1) == []

    # Test case 2: identificationModule is None
    api_studies_2 = [{"protocolSection": {"identificationModule": None}}]
    assert extract_trials(api_studies_2) == []

    # Test case 3: identity fields are None
    api_studies_3 = [
        {
            "protocolSection": {
                "identificationModule": {"nctId": None, "briefTitle": "Title"}
            }
        }
    ]
    assert extract_trials(api_studies_3) == []

    api_studies_4 = [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT12345678", "briefTitle": None}
            }
        }
    ]
    assert extract_trials(api_studies_4) == []


def test_api_nested_data_type_confusion():
    """Verify that malformed nested data (e.g. list where dict expected) doesn't crash."""
    trial = {"id": "NCT12345678", "name": "Test Trial"}

    # protocolSection is a list instead of a dict
    mock_data = {"protocolSection": []}
    with (
        patch("main.fetch_trial_data", return_value=mock_data),
        patch("main.save_snapshot"),
        patch("main.safe_json_load", return_value=[]),
        patch("main.update_history", return_value=[]),
    ):
        report, raw = process_trial(trial, "Target")
        assert report is not None
        assert report["sponsor"] == "N/A"
