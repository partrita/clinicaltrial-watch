import pytest
import os
import json
from unittest.mock import patch, MagicMock
from src.main import process_trial

def test_process_trial_malformed_api_data():
    """Verify that process_trial handles malformed nested API data without crashing."""
    trial_id = "NCT12345678"
    trial_config = {"id": trial_id, "name": "Test Trial"}

    # 1. API returns a string where a dictionary is expected (protocolSection)
    malformed_data_1 = {
        "id": trial_id,
        "protocolSection": "Not a dictionary"
    }

    # 2. API returns a string where a dictionary is expected (statusModule)
    malformed_data_2 = {
        "id": trial_id,
        "protocolSection": {
            "statusModule": "Not a dictionary"
        }
    }

    # 3. API returns a dictionary where a list is expected (primaryOutcomes)
    malformed_data_3 = {
        "id": trial_id,
        "protocolSection": {
            "outcomesModule": {
                "primaryOutcomes": {"not": "a list"}
            }
        }
    }

    # 4. API returns a list with non-dictionary elements where dicts are expected (primaryOutcomes[0])
    malformed_data_4 = {
        "id": trial_id,
        "protocolSection": {
            "outcomesModule": {
                "primaryOutcomes": ["Not a dictionary"]
            }
        }
    }

    # 5. API returns unexpected types for nested structures used in sponsors and dates
    malformed_data_5 = {
        "id": trial_id,
        "protocolSection": {
            "sponsorCollaboratorsModule": {"leadSponsor": "Not a dictionary"},
            "statusModule": {
                "startDateStruct": "Not a dictionary",
                "completionDateStruct": ["Not a dictionary"]
            },
            "designModule": {"enrollmentInfo": None}
        }
    }

    test_cases = [malformed_data_1, malformed_data_2, malformed_data_3, malformed_data_4, malformed_data_5]

    for i, malformed_data in enumerate(test_cases, 1):
        print(f"Testing malformed API data case {i}...")
        with patch("src.main.fetch_trial_data", return_value=malformed_data), \
             patch("src.main.update_history", return_value=[]), \
             patch("src.main.save_snapshot"), \
             patch("src.main.compare_snapshots", return_value=None):

            # This should not crash with AttributeError or TypeError
            report, raw = process_trial(trial_config, "TestTarget")

            assert report is not None
            assert raw is not None
            assert report["id"] == trial_id
            assert report["target"] == "TestTarget"

            # Verify default values are used for missing/malformed fields
            if i == 1:
                assert report["sponsor"] == "N/A"
                assert report["study_start"] == "N/A"
                assert report["enrollment"] == "N/A"
                assert report["primary_outcome"] == "N/A"
            elif i == 5:
                assert report["sponsor"] == "N/A"
                assert report["study_start"] == "N/A"
                assert report["enrollment"] == "N/A"
