import os
import yaml
import pytest
from src.manage_trials import add_to_exclusion_list, remove_trial, load_yaml
from src.update_trials_from_csv import load_yaml as load_yaml_csv

def test_add_to_exclusion_list_malformed_yaml(tmp_path):
    os.chdir(tmp_path)
    yaml_path = "excluded_trials.yaml"

    # Create malformed YAML (a list instead of a dict)
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("- item1\n- item2")

    # Should raise ValueError as it's not a dictionary
    with pytest.raises(ValueError, match="must be a dictionary"):
        add_to_exclusion_list("NCT12345678", yaml_path=yaml_path)

def test_load_yaml_malformed_trials_yaml(tmp_path):
    os.chdir(tmp_path)
    yaml_path = "trials.yaml"

    # Create malformed YAML (invalid syntax)
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("targets: [unclosed bracket")

    # Should raise YAMLError
    with pytest.raises(yaml.YAMLError):
        load_yaml(yaml_path)

def test_load_yaml_csv_malformed_trials_yaml(tmp_path):
    os.chdir(tmp_path)
    yaml_path = "trials.yaml"

    # Create malformed YAML (invalid syntax)
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("targets: [unclosed bracket")

    # Should raise YAMLError
    with pytest.raises(yaml.YAMLError):
        load_yaml_csv(yaml_path)

def test_remove_trial_invalid_id_format(tmp_path):
    assert remove_trial("not-an-id") is False

def test_add_to_exclusion_list_invalid_id(tmp_path):
    os.chdir(tmp_path)
    yaml_path = "excluded_trials.yaml"
    add_to_exclusion_list("not-an-id", yaml_path=yaml_path)
    assert not os.path.exists(yaml_path)
