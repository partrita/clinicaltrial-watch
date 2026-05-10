#!/usr/bin/env python3
"""
Update trials.yaml by adding trials from a CSV file to a specific target.
Usage: python update_trials_from_csv.py --target CCR8 --csv data/ctg-studies.csv
"""

import argparse
import csv
import os
from typing import Any, Dict, List, Optional

try:
    from utils import is_valid_nct_id, check_file_size
except ImportError:
    from src.utils import is_valid_nct_id, check_file_size

import yaml

# Configuration limits for DoS protection (CWE-400)
MAX_TARGETS = 100
MAX_TRIALS_PER_TARGET = 1000
MAX_CSV_ROWS = 5000
MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB


def load_yaml(yaml_path: str) -> Dict[str, Any]:
    """Load existing YAML file or return empty structure."""
    if not os.path.exists(yaml_path):
        return {"targets": []}

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(yaml_path)

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

    # Handle legacy format (flat trials list)
    if "trials" in data and "targets" not in data:
        print("Converting legacy format to target-based structure...")
        data = {
            "targets": [
                {
                    "name": "Default",
                    "description": "Migrated from legacy format",
                    "trials": data["trials"],
                }
            ]
        }

    # Handle old 'topics' naming
    if "topics" in data and "targets" not in data:
        data["targets"] = data.pop("topics")

    if "targets" in data and not isinstance(data["targets"], list):
        print(f"Error: 'targets' in {yaml_path} must be a list.")
        raise ValueError(f"'targets' in {yaml_path} must be a list")

    if "targets" not in data:
        data["targets"] = []

    return data


def save_yaml(data: Dict[str, Any], yaml_path: str) -> None:
    """Save YAML data to file."""
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    print(f"Saved to {yaml_path}")


def read_csv_trials(csv_path: str) -> List[Dict[str, str]]:
    """Read trials from CSV file."""
    if not os.path.exists(csv_path):
        return []

    # Security enhancement: Check file size before reading to prevent memory exhaustion DoS
    try:
        if os.path.getsize(csv_path) > MAX_CSV_SIZE:
            print(f"Error: CSV file too large: {csv_path}")
            return []
    except OSError as e:
        print(f"Error checking CSV file size: {e}")
        return []

    trials = []
    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row_count = 0
            for row in reader:
                row_count += 1
                if row_count > MAX_CSV_ROWS:
                    print(f"  Warning: CSV exceeds {MAX_CSV_ROWS} rows. Truncating.")
                    break

                nct_id = row.get("NCT Number", "").strip()
                title = row.get("Study Title", "").strip()
                if nct_id and title:
                    # Security enhancement: Truncate title to prevent DoS
                    title = title[:1000]
                    # Security enhancement: Validate NCT ID format
                    if is_valid_nct_id(nct_id):
                        trials.append({"id": nct_id, "name": title})
                    else:
                        print(f"  Warning: Skipping invalid NCT ID: {nct_id}")
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return trials


def update_target(
    data: Dict[str, Any],
    target_name: str,
    new_trials: List[Dict[str, str]],
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Update or create a target with new trials."""
    # Security enhancement: Truncate target name and description to prevent DoS
    target_name = str(target_name)[:255]
    if description:
        description = str(description)[:2000]

    # Find existing target
    target = None
    if "targets" not in data or not isinstance(data["targets"], list):
        data["targets"] = []

    for t in data["targets"]:
        if isinstance(t, dict) and str(t.get("name", ""))[:255].lower() == target_name.lower():
            target = t
            break

    # Create new target if not found
    if target is None:
        # Security enhancement: Limit number of targets to prevent DoS (CWE-400)
        if len(data["targets"]) >= MAX_TARGETS:
            print(f"Error: Maximum number of targets ({MAX_TARGETS}) reached. Cannot add '{target_name}'.")
            return data

        target = {
            "name": target_name,
            "description": description or f"{target_name} 타겟 임상시험 모니터링",
            "trials": [],
        }
        data["targets"].append(target)

    if "trials" not in target or not isinstance(target["trials"], list):
        target["trials"] = []

    # Get existing trial IDs
    existing_ids = {trial.get("id") for trial in target.get("trials", []) if isinstance(trial, dict) and trial.get("id")}

    # Load excluded trials
    excluded_ids = set()
    exclusion_yaml = "excluded_trials.yaml"
    if os.path.exists(exclusion_yaml):
        try:
            with open(exclusion_yaml, "r", encoding="utf-8") as f:
                ex_data = yaml.safe_load(f)
                if isinstance(ex_data, dict) and isinstance(ex_data.get("excluded_ids"), list):
                    excluded_ids = set(ex_data.get("excluded_ids", []))
        except (yaml.YAMLError, OSError) as e:
            print(f"Warning: Could not load exclusion list: {e}")

    # Add new trials
    added = 0
    for trial in new_trials:
        if not isinstance(trial, dict) or "id" not in trial:
            continue

        if trial["id"] in excluded_ids:
            # print(f"  Skipping excluded trial {trial['id']}")
            continue

        if trial["id"] not in existing_ids:
            # Security enhancement: Limit trials per target to prevent DoS (CWE-400)
            if len(target["trials"]) >= MAX_TRIALS_PER_TARGET:
                print(f"  Warning: Target '{target_name}' reached maximum trials ({MAX_TRIALS_PER_TARGET}).")
                break

            target["trials"].append(trial)
            existing_ids.add(trial["id"])
            added += 1

    print(
        f"Target '{target_name}': {added} new trials added, {len(target['trials'])} total"
    )
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update trials.yaml with trials from CSV"
    )
    parser.add_argument(
        "--target", "-t", required=True, help="Target name (e.g., CCR8, TIGIT)"
    )
    parser.add_argument(
        "--csv", "-c", default="data/ctg-studies.csv", help="Path to CSV file"
    )
    parser.add_argument(
        "--yaml", "-y", default="trials.yaml", help="Path to trials.yaml"
    )
    parser.add_argument(
        "--description", "-d", help="Target description (for new targets)"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing trials instead of adding",
    )

    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"Error: CSV file not found: {args.csv}")
        return 1

    # Load existing data
    data = load_yaml(args.yaml)

    # Read trials from CSV
    new_trials = read_csv_trials(args.csv)
    if not new_trials:
        print("No valid trials found in CSV.")
        return 1

    print(f"Found {len(new_trials)} trials in CSV")

    # If replace mode, clear existing trials for this target
    if args.replace:
        for target in data.get("targets", []):
            if isinstance(target, dict) and target.get("name", "").lower() == args.target.lower():
                target["trials"] = []
                break

    # Update target
    data = update_target(data, args.target, new_trials, args.description)

    # Save
    save_yaml(data, args.yaml)
    return 0


if __name__ == "__main__":
    exit(main())
