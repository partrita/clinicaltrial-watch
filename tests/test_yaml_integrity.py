import pytest
from src.main import load_config
from src.manage_trials import load_yaml as load_yaml_manage, add_to_exclusion_list
from src.update_trials_from_csv import load_yaml as load_yaml_update
from src.utils import sanitize_csv_value


def test_load_config_malformed_targets(tmp_path):
    """Verify that main.load_config raises ValueError if targets is not a list."""
    config_file = tmp_path / "trials.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("targets: not-a-list")

    with pytest.raises(ValueError, match="must be a list"):
        load_config(str(config_file))


def test_load_yaml_manage_malformed_targets(tmp_path):
    """Verify that manage_trials.load_yaml raises ValueError if targets is not a list."""
    config_file = tmp_path / "trials.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("targets: not-a-list")

    with pytest.raises(ValueError, match="must be a list"):
        load_yaml_manage(str(config_file))


def test_add_to_exclusion_list_malformed(tmp_path):
    """Verify that manage_trials.add_to_exclusion_list raises ValueError if excluded_ids is not a list."""
    exclusion_file = tmp_path / "excluded_trials.yaml"
    with open(exclusion_file, "w", encoding="utf-8") as f:
        f.write("excluded_ids: not-a-list")

    with pytest.raises(ValueError, match="must be a list"):
        add_to_exclusion_list("NCT12345678", yaml_path=str(exclusion_file))


def test_load_yaml_update_malformed_targets(tmp_path):
    """Verify that update_trials_from_csv.load_yaml raises ValueError if targets is not a list."""
    config_file = tmp_path / "trials.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("targets: not-a-list")

    with pytest.raises(ValueError, match="must be a list"):
        load_yaml_update(str(config_file))


def test_sanitize_csv_value_max_length_with_quote():
    """Verify that sanitize_csv_value stays within 32,767 chars even with a quote."""
    # Create a string that is 32,767 characters long and starts with '='
    long_val = "=" + ("A" * 32766)
    assert len(long_val) == 32767

    sanitized = sanitize_csv_value(long_val)
    # The result should have a leading quote, and its total length should be <= 32767
    assert sanitized.startswith("'")
    assert len(sanitized) <= 32767
    # It should contain as much of the original value as possible
    assert sanitized[1:] == long_val[:32766]
