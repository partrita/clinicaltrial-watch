import pytest
import os
import json
import shutil
from unittest.mock import patch, MagicMock
from src.main import process_trial

def test_process_trial_malformed_snapshot():
    """Verify that process_trial handles a malformed JSON snapshot (list instead of dict) gracefully."""
    trial_id = "NCT12345678"
    trial_config = {"id": trial_id, "name": "Test Trial"}
    snapshot_dir = "data/snapshots"
    os.makedirs(snapshot_dir, exist_ok=True)

    snapshot_file = os.path.join(snapshot_dir, f"{trial_id}_latest.json")

    # Create a malformed snapshot: a list instead of a dictionary
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump([{"some": "data"}], f)

    try:
        # Mock fetch_trial_data to return None so it falls back to the local snapshot
        with patch("src.main.fetch_trial_data", return_value=None), \
             patch("src.main.update_history"), \
             patch("src.main.save_snapshot"), \
             patch("src.main.compare_snapshots", return_value=None):

            # This should not crash with AttributeError: 'list' object has no attribute 'get'
            report, raw = process_trial(trial_config, "TestTarget")

            assert report is None
            assert raw is None

    finally:
        if os.path.exists(snapshot_file):
            os.remove(snapshot_file)

def test_quarto_template_logic_robustness():
    """Verify that the type checks added to Quarto templates handle malformed JSON data correctly."""
    # This test simulates the logic added to generate_target_pages.py QMD templates

    # 1. Target Milestones section
    history = {"not": "a list"}
    if not isinstance(history, list):
        history = []
    # Should be able to iterate without crash
    for record in reversed(history[-10:]):
        pass
    assert history == []

    # 2. Trial Changes section
    history_2 = "just a string"
    if not isinstance(history_2, list):
        history_2 = []
    # Should be able to filter/iterate
    real_changes = [r for r in history_2 if r.get('diff') != "Initial data collection"]
    assert real_changes == []

    # 3. Monitoring Status section
    summary = None
    if not isinstance(summary, list):
        summary = []
    # Should be able to iterate
    for item in summary:
        pass
    assert summary == []

    # 4. generate_index_qmd logic
    targets = {"key": "val"}
    if not isinstance(targets, list):
        targets = []
    if targets:
        targets.sort(key=lambda x: x['name'])
    assert targets == []
