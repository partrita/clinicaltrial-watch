#!/usr/bin/env python3
"""
Management script for clinical trials.
Allows removing NCT codes from tracking and cleaning up associated data.
"""

import argparse
import os
import json
from typing import Any, Dict, Optional
from utils import sanitize_id, is_valid_nct_id, check_file_size
from generate_target_pages import main as generate_pages

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Configuration limits for DoS protection (CWE-400)
MAX_EXCLUDED_IDS = 5000


def load_yaml(yaml_path: str = "trials.yaml") -> Dict[str, Any]:
    """Load trials configuration from YAML file."""
    if not os.path.exists(yaml_path):
        return {"targets": []}

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(yaml_path)

    if HAS_YAML:
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            return {"targets": []}
        except (yaml.YAMLError, OSError) as e:
            print(f"Error: Failed to load {yaml_path}: {e}")
            raise

        if data is None:
            return {"targets": []}

        if not isinstance(data, dict):
            print(f"Error: {yaml_path} is not a valid YAML dictionary.")
            raise ValueError(f"{yaml_path} must be a dictionary")

        if "targets" in data and not isinstance(data["targets"], list):
            print(f"Error: 'targets' in {yaml_path} must be a list.")
            raise ValueError(f"'targets' in {yaml_path} must be a list")

        if "targets" not in data:
            data["targets"] = []
        return data
    else:
        # Simplistic fallback isn't ideal here for writing back
        raise ImportError(
            "The 'yaml' (PyYAML) module is required for reliable management."
        )


def save_yaml(data: Dict[str, Any], yaml_path: str = "trials.yaml") -> None:
    """Save YAML data to file."""
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    print(f"Updated {yaml_path}")


def add_to_exclusion_list(trial_id: str, yaml_path: str = "excluded_trials.yaml"):
    """Add a trial ID to the exclusion list."""
    if not HAS_YAML:
        print("Warning: Cannot update exclusion list because 'yaml' module is missing.")
        return

    # Security enhancement: Validate NCT ID format before adding to exclusion list
    if not is_valid_nct_id(trial_id):
        print(f"Warning: Invalid NCT ID format, not adding to exclusion: {trial_id}")
        return

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(yaml_path)

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        data = {"excluded_ids": []}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        print(f"Error: Failed to load {yaml_path}: {e}")
        raise

    if data is None:
        data = {"excluded_ids": []}

    if not isinstance(data, dict):
        print(f"Error: {yaml_path} is not a valid YAML dictionary.")
        raise ValueError(f"{yaml_path} must be a dictionary")

    if "excluded_ids" in data and not isinstance(data["excluded_ids"], list):
        print(f"Error: 'excluded_ids' in {yaml_path} must be a list.")
        raise ValueError(f"'excluded_ids' in {yaml_path} must be a list")

    if "excluded_ids" not in data:
        data["excluded_ids"] = []

    if trial_id not in data["excluded_ids"]:
        # Security enhancement: Limit number of excluded trials to prevent DoS (CWE-400)
        if len(data["excluded_ids"]) >= MAX_EXCLUDED_IDS:
            print(f"Warning: Exclusion list has reached maximum capacity ({MAX_EXCLUDED_IDS}). Cannot add {trial_id}.")
            return

        data["excluded_ids"].append(trial_id)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )
        print(f"Added {trial_id} to exclusion list ({yaml_path})")


def remove_trial(
    trial_id: str, target_name: Optional[str] = None, cleanup: bool = False
):
    """Remove a trial by ID from trials.yaml and optionally clean up data."""
    # Security enhancement: Validate NCT ID format
    if not is_valid_nct_id(trial_id):
        print(f"Error: Invalid NCT ID format: {trial_id}")
        return False

    data = load_yaml()
    targets = data.get("targets", [])

    found = False
    new_targets = []

    for target in targets:
        if not isinstance(target, dict):
            continue
        if target_name and target.get("name", "").lower() != target_name.lower():
            new_targets.append(target)
            continue

        original_count = len(target.get("trials", []))
        target["trials"] = [t for t in target.get("trials", []) if isinstance(t, dict) and t.get("id") != trial_id]

        if len(target["trials"]) < original_count:
            found = True
            print(f"Removed {trial_id} from target '{target.get('name', 'Unknown')}'")

        new_targets.append(target)

    if not found:
        print(
            f"Trial ID '{trial_id}' not found in {'target ' + target_name if target_name else 'any targets'}."
        )
        return False

    data["targets"] = new_targets
    save_yaml(data)

    # Add to exclusion list
    add_to_exclusion_list(trial_id)

    if cleanup:
        perform_cleanup(trial_id)

    # Refresh website pages
    print("Refreshing target pages...")
    generate_pages()
    return True


def perform_cleanup(trial_id: str):
    """Clean up data files associated with a trial ID."""
    safe_id = sanitize_id(trial_id)
    files_to_delete = [
        f"data/snapshots/{safe_id}_latest.json",
        f"data/history/{safe_id}_history.json",
    ]

    for file_path in files_to_delete:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted {file_path}")

    # Remove from status_summary.json in all target folders
    targets_base = "data/targets"
    if os.path.exists(targets_base):
        for target_dir in os.listdir(targets_base):
            summary_path = os.path.join(targets_base, target_dir, "status_summary.json")
            if os.path.exists(summary_path):
                try:
                    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
                    check_file_size(summary_path)

                    with open(summary_path, "r", encoding="utf-8") as f:
                        summary = json.load(f)

                    if not isinstance(summary, list):
                        raise ValueError(f"{summary_path} is not a JSON list")

                    new_summary = [
                        item for item in summary if isinstance(item, dict) and item.get("id") != trial_id
                    ]

                    if len(new_summary) < len(summary):
                        with open(summary_path, "w", encoding="utf-8") as f:
                            # Optimized: Removed indent for performance and smaller file sizes
                            json.dump(new_summary, f, ensure_ascii=False)
                        print(f"Updated {summary_path}")
                except Exception as e:
                    print(f"Error updating {summary_path}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Manage clinical trials configuration."
    )
    subparsers = parser.add_subparsers(dest="command", help="Management commands")

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove a trial NCP code")
    remove_parser.add_argument(
        "--id", required=True, help="Trial ID (NCT code) to remove"
    )
    remove_parser.add_argument(
        "--target", help="Specific target to remove from (optional)"
    )
    remove_parser.add_argument(
        "--cleanup", action="store_true", help="Delete associated data files"
    )

    args = parser.parse_args()

    if args.command == "remove":
        remove_trial(args.id, target_name=args.target, cleanup=args.cleanup)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
