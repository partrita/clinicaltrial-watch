import pytest
import os
import json
import shutil
from unittest.mock import patch, MagicMock
from src.main import process_trial

def test_process_trial_history_type_crash():
    """Confirm that process_trial crashes when history file is a dictionary instead of a list."""
    trial_id = "NCT00000001"
    trial_config = {"id": trial_id, "name": "Test Trial"}
    history_dir = "data/history"
    os.makedirs(history_dir, exist_ok=True)

    history_file = os.path.join(history_dir, f"{trial_id}_history.json")

    # Corrupt history: dictionary instead of list
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump({"corrupted": "data"}, f)

    try:
        # Mock dependencies to reach the vulnerable 'if history:' block
        with patch("src.main.fetch_trial_data") as mock_fetch, \
             patch("src.main.compare_snapshots", return_value=None), \
             patch("src.main.save_snapshot"):

            mock_fetch.return_value = {
                "protocolSection": {
                    "identificationModule": {"nctId": trial_id, "briefTitle": "Title"},
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor"}},
                    "designModule": {"enrollmentInfo": {"count": 100}, "phases": ["PHASE1"]},
                    "conditionsModule": {"conditions": ["Condition"]},
                    "descriptionModule": {"briefSummary": "Summary"}
                }
            }

            # This is expected to crash with KeyError: -1 or similar before fix
            process_trial(trial_config, "TestTarget")

    finally:
        if os.path.exists(history_file):
            os.remove(history_file)
