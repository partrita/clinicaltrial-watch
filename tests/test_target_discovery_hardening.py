import json
import os

import pytest
import yaml

from src.generate_target_pages import discover_all_targets


@pytest.fixture
def mock_config(tmp_path):
    """Create a temporary trials.yaml and data directory."""
    config_path = tmp_path / "trials.yaml"
    targets_dir = tmp_path / "data" / "targets"
    targets_dir.mkdir(parents=True)

    # Change current working directory to tmp_path for the test
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    yield config_path, targets_dir

    # Restore CWD
    os.chdir(old_cwd)


def test_target_discovery_collision_deduplication(mock_config):
    """Verify that targets with colliding sanitized IDs are deduplicated."""
    config_path, _ = mock_config

    # "Target A" and "Target!A" both resolve to "target_a" via sanitize_id
    config = {
        "targets": [
            {"name": "Target A", "description": "Desc 1"},
            {"name": "Target!A", "description": "Desc 2"},
        ]
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f)

    targets = discover_all_targets()

    # Should only have 1 target because of ID collision
    assert len(targets) == 1
    assert targets[0]["name"] == "Target A"


def test_target_discovery_resource_limit(mock_config):
    """Verify that target discovery respects the 100-target limit from trials.yaml."""
    config_path, _ = mock_config

    # Create 150 targets
    config = {
        "targets": [
            {"name": f"Target {i}", "description": f"Desc {i}"} for i in range(150)
        ]
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f)

    targets = discover_all_targets()

    # Should be capped at 100
    assert len(targets) == 100


def test_target_discovery_filesystem_deduplication(mock_config):
    """Verify that discovery from filesystem doesn't add duplicates already in trials.yaml."""
    config_path, targets_dir = mock_config

    # Target in trials.yaml
    config = {"targets": [{"name": "Target A", "description": "YAML Desc"}]}
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Same target (by sanitized ID) in filesystem
    # Sanitized ID of "Target A" is "target_a"
    # Even if directory is "target!a", it should resolve to "target_a" and be skipped
    t_dir = targets_dir / "target!a"
    t_dir.mkdir()
    summary = [{"target": "Target!A", "id": "NCT00000001"}]
    with open(t_dir / "status_summary.json", "w") as f:
        json.dump(summary, f)

    targets = discover_all_targets()

    # Should only have 1 target, and it should be the one from trials.yaml (highest precedence)
    assert len(targets) == 1
    assert targets[0]["name"] == "Target A"


def test_target_discovery_total_resource_limit(mock_config):
    """Verify that the 100-target limit applies across both discovery sources."""
    config_path, targets_dir = mock_config

    # 60 targets in trials.yaml
    config = {
        "targets": [{"name": f"YAML Target {i}", "id": f"NCT{i:08}"} for i in range(60)]
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # 60 targets in filesystem
    for i in range(60):
        t_dir = targets_dir / f"FS_Target_{i}"
        t_dir.mkdir()
        summary = [{"target": f"FS Target {i}", "id": f"NCT1{i:07}"}]
        with open(t_dir / "status_summary.json", "w") as f:
            json.dump(summary, f)

    targets = discover_all_targets()

    # Total should be capped at 100
    assert len(targets) == 100

    # Precedence: YAML targets (60) + first 40 FS targets
    yaml_targets = [t for t in targets if "YAML Target" in t["name"]]
    fs_targets = [t for t in targets if "FS Target" in t["name"]]

    assert len(yaml_targets) == 60
    assert len(fs_targets) == 40
