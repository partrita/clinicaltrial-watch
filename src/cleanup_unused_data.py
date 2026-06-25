import os
import re
import yaml
from typing import Set


def get_valid_nct_ids(yaml_path: str = "trials.yaml") -> Set[str]:
    """Extract all valid NCT IDs from trials.yaml."""
    if not os.path.exists(yaml_path):
        print(f"Error: {yaml_path} not found.")
        return set()

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading {yaml_path}: {e}")
        return set()

    nct_ids = set()
    for target in config.get("targets", []):
        if not isinstance(target, dict):
            continue
        for trial in target.get("trials", []):
            if not isinstance(trial, dict):
                continue
            trial_id = trial.get("id")
            if trial_id and isinstance(trial_id, str) and trial_id.startswith("NCT"):
                nct_ids.add(trial_id.strip())

    return nct_ids


def cleanup_directory(
    directory: str, pattern: str, valid_ids: Set[str], dry_run: bool = True
) -> None:
    """Remove files in directory matching pattern if the NCT ID is not in valid_ids."""
    if not os.path.exists(directory):
        print(f"Directory {directory} does not exist. Skipping.")
        return

    print(f"\nScanning directory: {directory} (dry_run={dry_run})")

    try:
        filenames = os.listdir(directory)
    except OSError as e:
        print(f"Error reading directory {directory}: {e}")
        return

    removed_count = 0
    compiled_pattern = re.compile(pattern)

    for filename in sorted(filenames):
        match = compiled_pattern.match(filename)
        if match:
            nct_id = match.group(1)
            if nct_id not in valid_ids:
                file_path = os.path.join(directory, filename)
                if dry_run:
                    print(f"[DRY-RUN] Would remove: {file_path}")
                else:
                    try:
                        os.remove(file_path)
                        print(f"Removed: {file_path}")
                    except OSError as e:
                        print(f"Error removing {file_path}: {e}")
                removed_count += 1

    print(f"Scan complete. Total files matching cleanup condition: {removed_count}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up data files for NCT IDs not present in trials.yaml"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform actual deletion instead of dry run",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    valid_ids = get_valid_nct_ids()
    print(f"Found {len(valid_ids)} valid NCT IDs in trials.yaml")
    if not valid_ids:
        print(
            "No valid NCT IDs found. Aborting cleanup to prevent accidental data loss."
        )
        return

    # Clean up data/history: files matching NCT\d+_history.json
    cleanup_directory(
        "data/history", r"^(NCT\d+)_history\.json$", valid_ids, dry_run=dry_run
    )

    # Clean up data/snapshots: files matching NCT\d+_latest.json
    cleanup_directory(
        "data/snapshots", r"^(NCT\d+)_latest\.json$", valid_ids, dry_run=dry_run
    )

    # Also clean up trials/: QMD files matching NCT\d+.qmd (if they are obsolete)
    cleanup_directory("trials", r"^(NCT\d+)\.qmd$", valid_ids, dry_run=dry_run)


if __name__ == "__main__":
    main()
