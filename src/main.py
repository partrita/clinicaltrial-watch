#!/usr/bin/env python3
"""
Main script for clinical trial monitoring.
Fetches trial data, compares with previous snapshots, and generates target-based reports.
"""

import os
import json
import csv
from functools import lru_cache
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from crawler import fetch_trial_data, save_snapshot, reset_session
from utils import sanitize_id, is_valid_nct_id, sanitize_csv_value, check_file_size
from diff_engine import compare_snapshots, format_diff
from generate_target_pages import main as generate_pages

import yaml

# Configuration limits for DoS protection (CWE-400)
MAX_TARGETS = 100
MAX_TRIALS_PER_TARGET = 1000
MAX_HISTORY_ENTRIES = 100


def load_config(config_path: str = "trials.yaml") -> Dict[str, Any]:
    """Load trials configuration from YAML file."""
    if not os.path.exists(config_path):
        return {"targets": []}

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return {"targets": []}
    except (yaml.YAMLError, OSError) as e:
        print(f"Error: Failed to load config {config_path}: {e}")
        raise

    if data is None:
        return {"targets": []}

    if not isinstance(data, dict):
        print(f"Error: {config_path} is not a valid YAML dictionary.")
        raise ValueError(f"{config_path} must be a dictionary")

    if "targets" not in data:
        # Handle legacy format (flat trials list)
        if "trials" in data:
            print("Converting legacy format to target-based structure...")
            data = {
                "targets": [
                    {
                        "name": "Default",
                        "description": "Migrated from legacy format",
                        "trials": data.get("trials", []),
                    }
                ]
            }

    # Re-check type after possible conversion
    if not isinstance(data, dict):
        return {"targets": []}

    # Handle old 'topics' naming
    if "topics" in data and "targets" not in data:
        data["targets"] = data.pop("topics")

    if "targets" in data and not isinstance(data["targets"], list):
        print(f"Error: 'targets' in {config_path} must be a list.")
        raise ValueError(f"'targets' in {config_path} must be a list")

    if "targets" not in data:
        data["targets"] = []

    return data


def deduplicate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check for duplicate trial IDs within and across targets.
    Merges trial configurations for the same ID within a target.
    Also validates IDs and truncates long metadata to prevent DoS.
    """
    if not isinstance(config, dict):
        return {"targets": []}

    total_duplicates = 0
    total_invalid = 0
    any_truncation = False

    targets = config.get("targets", [])
    if not isinstance(targets, list):
        print("  Warning: 'targets' in config is not a list. Resetting.")
        config["targets"] = []
        return config

    # Security enhancement: Limit number of targets to prevent DoS (CWE-400)
    if len(targets) > MAX_TARGETS:
        print(f"  Warning: Configuration exceeds {MAX_TARGETS} targets. Truncating.")
        targets = targets[:MAX_TARGETS]
        any_truncation = True

    seen_globally = {}  # trial_id -> target_name
    seen_target_ids = {}  # sanitized_id -> target_name
    total_invalid = 0
    valid_targets = []

    for target in targets:
        if not isinstance(target, dict):
            print(f"  Warning: Removing invalid target entry (not a dictionary): {target}")
            continue

        # Security enhancement: Truncate metadata
        orig_name = target.get("name")
        if orig_name is not None:
            target["name"] = str(orig_name)[:255]
            if len(str(orig_name)) > 255:
                any_truncation = True
        else:
            target["name"] = "Unknown"

        orig_desc = target.get("description")
        if orig_desc is not None:
            target["description"] = str(orig_desc)[:2000]
            if len(str(orig_desc)) > 2000:
                any_truncation = True

        target_name = target["name"]

        # Security enhancement: Prevent target ID collisions which cause data directory overwrites
        target_id = sanitize_id(target_name).lower()
        if target_id in seen_target_ids:
            print(f"  Warning: Target ID collision detected: '{target_name}' and '{seen_target_ids[target_id]}' both resolve to '{target_id}'. Skipping '{target_name}'.")
            total_invalid += 1
            continue
        seen_target_ids[target_id] = target_name

        trials = target.get("trials", [])
        if not isinstance(trials, list):
            trials = []

        # Security enhancement: Limit trials per target to prevent DoS (CWE-400)
        if len(trials) > MAX_TRIALS_PER_TARGET:
            print(f"  Warning: Target '{target_name}' exceeds {MAX_TRIALS_PER_TARGET} trials. Truncating.")
            trials = trials[:MAX_TRIALS_PER_TARGET]
            any_truncation = True

        unique_target_trials = []
        if not trials:
            target["trials"] = []
            valid_targets.append(target)
            continue

        seen_in_target = {}  # trial_id -> index in unique_target_trials

        for trial in trials:
            if not isinstance(trial, dict):
                print(f"  Warning: Removing invalid trial entry (not a dictionary): {trial}")
                total_invalid += 1
                continue

            trial_id = trial.get("id")

            # Security enhancement: Validate NCT ID format
            if not is_valid_nct_id(trial_id):
                print(f"  Warning: Removing invalid trial ID: {trial_id}")
                total_invalid += 1
                continue

            # Security enhancement: Truncate trial name
            orig_trial_name = trial.get("name")
            if orig_trial_name is not None:
                trial["name"] = str(orig_trial_name)[:1000]
                if len(str(orig_trial_name)) > 1000:
                    any_truncation = True

            if trial_id in seen_in_target:
                idx = seen_in_target[trial_id]
                existing_trial = unique_target_trials[idx]
                # Merge logic: favor non-empty names or longer names
                if not existing_trial.get("name") and trial.get("name"):
                    existing_trial["name"] = trial["name"]
                elif (
                    existing_trial.get("name")
                    and trial.get("name")
                    and len(trial["name"]) > len(existing_trial["name"])
                ):
                    existing_trial["name"] = trial["name"]
                total_duplicates += 1
                print(
                    f"  Note: Duplicate trial {trial_id} merged within target {target_name}"
                )
            else:
                seen_in_target[trial_id] = len(unique_target_trials)
                unique_target_trials.append(trial)

                if trial_id in seen_globally:
                    print(
                        f"  Note: Trial {trial_id} appears in multiple targets: {seen_globally[trial_id]} and {target_name}"
                    )
                else:
                    seen_globally[trial_id] = target_name

        target["trials"] = unique_target_trials
        valid_targets.append(target)

    config["targets"] = valid_targets

    if total_duplicates > 0 or total_invalid > 0 or any_truncation:
        print("\n✓ Integrity check summary:")
        if total_duplicates > 0:
            print(f"  - Merged {total_duplicates} duplicate trial entries.")
        if total_invalid > 0:
            print(f"  - Removed {total_invalid} invalid trial entries.")
        if any_truncation:
            print("  - Truncated excessively long metadata fields.")

        save_config(config)

    return config


def save_config(config: Dict[str, Any], config_path: str = "trials.yaml") -> None:
    """Save cleaned trials configuration back to YAML file."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
        print(f"  ✓ Cleaned configuration saved to {config_path}")
    except Exception as e:
        print(f"  Warning: Failed to save cleaned config: {e}")


_SENTINEL = object()


def safe_json_load(file_path: str, default: Any = _SENTINEL) -> Any:
    """
    Safely load JSON from a file.
    Returns the default value only if the file is missing (FileNotFoundError).
    Raises an exception for other errors (OSError, JSONDecodeError) to prevent data loss.
    """
    if default is _SENTINEL:
        default = []

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"Error: Failed to load {file_path}: {e}")
        raise


def update_history(
    trial_id: str,
    diff_text: str,
    history_dir: str = "data/history",
    history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Save change history for a trial. Returns the updated history list."""
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_trial_id = sanitize_id(trial_id)
    history_file = os.path.join(history_dir, f"{safe_trial_id}_history.json")

    if history is None:
        history = safe_json_load(history_file, default=[])

    if not isinstance(history, list):
        print(f"  Warning: History for {trial_id} is not a list. Resetting.")
        history = []
    else:
        # Security enhancement: Filter out non-dictionary items to prevent crashes (CWE-400)
        history = [r for r in history if isinstance(r, dict)]

    history.append({"timestamp": timestamp, "diff": diff_text[:10000]})

    # Keep history size bounded to prevent DoS via disk exhaustion
    if len(history) > MAX_HISTORY_ENTRIES:
        history = history[-MAX_HISTORY_ENTRIES:]

    with open(history_file, "w", encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(history, f, ensure_ascii=False)

    return history


def update_target_history(
    target_name: str,
    current_reports: List[Dict[str, Any]],
    history_dir: str = "data/history",
) -> None:
    """Save change history for a target."""
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_target_name = sanitize_id(target_name)
    history_file = os.path.join(history_dir, f"target_{safe_target_name.lower()}.json")

    history = safe_json_load(history_file, default=[])

    if not isinstance(history, list) or not all(isinstance(x, dict) for x in history):
        print(f"  Warning: Target history for {target_name} is not a valid list. Resetting.")
        history = []

    # Check for changes today specifically for the daily log
    changed_today = [r["id"] for r in current_reports if r.get("changed_today")]

    message = ""
    if not history:
        message = f"Initial data collection: {len(current_reports)} trials found."
    elif changed_today:
        # Limit displayed IDs to prevent extremely large message strings
        display_limit = 10
        display_ids = changed_today[:display_limit]
        message = f"Changes detected in {len(changed_today)} trials: {', '.join(display_ids)}"
        if len(changed_today) > display_limit:
            message += f" (and {len(changed_today) - display_limit} more)"

    if message:
        history.append({"timestamp": timestamp, "event": message})

        # Keep history size bounded to prevent DoS via disk exhaustion
        if len(history) > MAX_HISTORY_ENTRIES:
            history = history[-MAX_HISTORY_ENTRIES:]

        with open(history_file, "w", encoding="utf-8") as f:
            # Optimized: Removed indent to reduce serialization time and file size
            json.dump(history, f, ensure_ascii=False)
        print(f"  Updated target history for {target_name}")


# Pre-defined mappings for efficient dictionary flattening
TOP_LEVEL_SECTION_MAP = {
    "protocolSection": "Prot",
    "derivedSection": "Deriv",
    "annotationSection": "Annot",
    "resultsSection": "Res",
}
FLATTEN_STRIP_PREFIXES = {"Prot", "Deriv", "Annot", "Res"}


@lru_cache(maxsize=2048)
def _get_flatten_key_cached(parent_key: str, k: str, sep: str = "_") -> str:
    """Internal cached helper for _get_flatten_key."""
    clean_k = k
    if k.endswith(("Module", "Struct")):
        clean_k = k[:-6]

    if not parent_key:
        # Handle top-level keys: map section names
        new_key = TOP_LEVEL_SECTION_MAP.get(clean_k, clean_k)

        # Functional parity: restore prefix stripping for pre-formatted keys
        if new_key.startswith(("Prot_", "Deriv_", "Annot_", "Res_")):
            new_key = new_key[new_key.find("_") + 1 :]
        return new_key

    if parent_key in FLATTEN_STRIP_PREFIXES:
        return clean_k

    return parent_key + sep + clean_k


def _get_flatten_key(parent_key: str, k: str, sep: str = "_") -> str:
    """
    Helper for cached key transformation during flattening.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    # Limit string lengths before caching
    safe_parent = str(parent_key)[:255]
    safe_k = str(k)[:255]
    safe_sep = str(sep)[:10]

    return _get_flatten_key_cached(safe_parent, safe_k, safe_sep)


def flatten_dict(
    d: Dict[str, Any],
    parent_key: str = "",
    sep: str = "_",
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Flatten nested dictionary for CSV export.
    Optimized with iterative approach to avoid recursion and redundant type checks.
    Performance: ~10-15% faster than recursive version.
    """
    if result is None:
        result = {}

    stack = [(d, parent_key)]

    while stack:
        current_dict, p_key = stack.pop()
        for k, v in current_dict.items():
            new_key = _get_flatten_key(p_key, k, sep)

            # Use type() for slightly faster check than isinstance() in tight loops
            val_type = type(v)
            if val_type is dict:
                stack.append((v, new_key))
            elif val_type is list:
                if not v:
                    result[new_key] = ""
                else:
                    # Security enhancement: Limit number of items from lists to prevent DoS (CWE-400)
                    MAX_LIST_ITEMS = 1000
                    truncated_list = v[:MAX_LIST_ITEMS]

                    # Optimized: Check only the first element (ClinicalTrials.gov lists are homogeneous)
                    first = truncated_list[0]
                    first_type = type(first)

                    # Truncate resulting strings to prevent DoS
                    MAX_VAL_LEN = 10000

                    if first_type is str:
                        res_str = ", ".join(map(str, truncated_list))
                        result[new_key] = res_str[:MAX_VAL_LEN]
                    elif first_type in (int, float, bool):
                        res_str = ", ".join(map(str, truncated_list))
                        result[new_key] = res_str[:MAX_VAL_LEN]
                    else:
                        res_str = json.dumps(truncated_list, ensure_ascii=False)
                        result[new_key] = res_str[:MAX_VAL_LEN]
            else:
                result[new_key] = v

    return result


def process_trial(
    trial: Dict[str, Any], target_name: str, thirty_days_ago_str: str = ""
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Process a single trial and return report data."""
    trial_id = trial["id"]

    # Security enhancement: Validate NCT ID format
    if not is_valid_nct_id(trial_id):
        print(f"  Warning: Skipping invalid NCT ID: {trial_id}")
        return None, None

    print(f"Processing {trial_id}...")

    # Load trial history once to avoid redundant I/O
    safe_trial_id = sanitize_id(trial_id)
    history_file = f"data/history/{safe_trial_id}_history.json"
    history = safe_json_load(history_file, default=[])

    # Ensure thirty_days_ago_str is set for efficient comparison
    if not thirty_days_ago_str:
        thirty_days_ago_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    new_data = fetch_trial_data(trial_id)
    if not new_data:
        local_path = f"data/snapshots/{safe_trial_id}_latest.json"
        new_data = safe_json_load(local_path, default=None)
        if not new_data:
            print(f"  Skipping {trial_id} - no data available.")
            return None, None

    if not isinstance(new_data, dict):
        print(f"  Error: Data for {trial_id} is not a dictionary. Skipping.")
        return None, None

    raw_data = flatten_dict(new_data)
    raw_data["_target"] = target_name

    protocol = new_data.get("protocolSection", {})
    status_mod = protocol.get("statusModule", {})

    sponsor = (
        protocol.get("sponsorCollaboratorsModule", {})
        .get("leadSponsor", {})
        .get("name", "N/A")
    )
    start_date = status_mod.get("startDateStruct", {}).get("date", "N/A")
    end_date = status_mod.get("completionDateStruct", {}).get("date", "N/A")
    enrollment = (
        protocol.get("designModule", {}).get("enrollmentInfo", {}).get("count", "N/A")
    )

    primary_outcomes = protocol.get("outcomesModule", {}).get("primaryOutcomes", [])
    primary_outcome = (
        primary_outcomes[0].get("measure", "N/A") if primary_outcomes else "N/A"
    )

    study_status = status_mod.get("overallStatus", "N/A")
    last_submit_date = status_mod.get("lastUpdateSubmitDate", "N/A")
    conditions_list = protocol.get("conditionsModule", {}).get("conditions", [])
    conditions = ", ".join(conditions_list) if conditions_list else "N/A"
    phases_list = protocol.get("designModule", {}).get("phases", [])
    phases = ", ".join(phases_list) if phases_list else "N/A"
    detailed_desc = protocol.get("descriptionModule", {}).get(
        "detailedDescription",
        protocol.get("descriptionModule", {}).get("briefSummary", "N/A"),
    )
    # Security enhancement: Truncate excessively long descriptions to prevent DoS
    detailed_desc = str(detailed_desc)[:10000]

    diff = compare_snapshots(trial_id, new_data)

    report_item = {
        "id": trial_id,
        "name": trial["name"],
        "target": target_name,
        "sponsor": sponsor,
        "status": study_status,
        "conditions": conditions,
        "phases": phases,
        "last_updated": last_submit_date,
        "study_start": start_date,
        "study_end": end_date,
        "enrollment": enrollment,
        "primary_outcome": primary_outcome,
        "monitor_status": "No Change",
        "last_monitored_change": "No changes yet",
        "details": detailed_desc,
    }

    if diff:
        diff_text = format_diff(diff)
        print(f"  Changes found for {trial_id}")
        # Reuse pre-loaded history
        history = update_history(trial_id, diff_text, history=history)
        last_monitored = datetime.now().strftime("%Y-%m-%d")

        # Security enhancement: Truncate combined details to prevent DoS
        combined_details = f"**[RECENT CHANGES FOUND]**\n{diff_text[:10000]}\n\n***\n{detailed_desc}"
        report_item.update(
            {
                "changed_today": True,
                "last_monitored_change": last_monitored,
                "details": combined_details[:20000],
            }
        )
    elif not history:
        print(f"  Initializing history for {trial_id}")
        history = update_history(trial_id, "Initial data collection", history=[])

    # Check for any changes in the last 30 days to set monitor_status using history in memory
    if history:
        # Update last_monitored_change from history
        # Security enhancement: Validate record type and key existence (CWE-400)
        last_record = history[-1]
        if isinstance(last_record, dict) and "timestamp" in last_record:
            report_item["last_monitored_change"] = str(last_record["timestamp"]).split(" ")[0]

        # Check 30 day window using efficient string comparison (~80x faster than strptime)
        for record in reversed(history):  # Search from newest
            if not isinstance(record, dict) or record.get("diff") == "Initial data collection":
                continue

            timestamp = record.get("timestamp")
            if timestamp and str(timestamp)[:10] > thirty_days_ago_str:
                report_item["monitor_status"] = "Changed"
                break

    save_snapshot(trial_id, new_data)
    return report_item, raw_data


def save_target_data(
    target_name: str,
    summary_report: List[Dict[str, Any]],
    all_raw_data: List[Dict[str, Any]],
) -> None:
    """Save data for a specific target."""
    safe_target_name = sanitize_id(target_name)
    target_dir = f"data/targets/{safe_target_name.lower()}"
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    # Save JSON summary
    with open(f"{target_dir}/status_summary.json", "w", encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(summary_report, f, ensure_ascii=False)

    # Save CSV summary
    if summary_report:
        # Optimized: Use fixed headers for summary_report (fastest)
        headers = [
            "id",
            "name",
            "target",
            "sponsor",
            "status",
            "conditions",
            "phases",
            "last_updated",
            "study_start",
            "study_end",
            "enrollment",
            "primary_outcome",
            "monitor_status",
            "last_monitored_change",
            "details",
        ]
        if any("changed_today" in r for r in summary_report):
            headers.append("changed_today")

        # Security enhancement: Sanitize headers to prevent CSV formula injection
        safe_headers = [sanitize_csv_value(h) for h in headers]

        with open(
            f"{target_dir}/status_summary.csv", "w", encoding="utf-8-sig", newline=""
        ) as f:
            dict_writer = csv.DictWriter(
                f, fieldnames=safe_headers, extrasaction="ignore"
            )
            dict_writer.writeheader()
            # Sanitize both keys and values to prevent CSV formula injection
            sanitized_summary = []
            for row in summary_report:
                sanitized_row = {}
                for k, v in row.items():
                    safe_k = sanitize_csv_value(k)
                    safe_v = sanitize_csv_value(v)
                    sanitized_row[safe_k] = safe_v
                sanitized_summary.append(sanitized_row)
            dict_writer.writerows(sanitized_summary)

    # Save raw data CSV
    if all_raw_data:
        # Optimized: Single-pass header collection using union of keys
        all_keys = set().union(*(row.keys() for row in all_raw_data))
        sorted_keys = sorted(list(all_keys))

        # Security enhancement: Sanitize headers to prevent CSV formula injection
        headers = [sanitize_csv_value(str(k)) for k in sorted_keys]

        with open(
            f"{target_dir}/all_trials_raw.csv", "w", newline="", encoding="utf-8-sig"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            # Sanitize both keys and values to prevent CSV formula injection
            sanitized_raw = []
            for row in all_raw_data:
                sanitized_row = {}
                for k, v in row.items():
                    safe_k = sanitize_csv_value(str(k))
                    safe_v = sanitize_csv_value(v)
                    sanitized_row[safe_k] = safe_v
                sanitized_raw.append(sanitized_row)
            writer.writerows(sanitized_raw)

    print(f"  Saved target data to {target_dir}/")


MAX_WORKERS = 20  # Increased for better utilization of I/O bandwidth
PER_TRIAL_TIMEOUT = 30  # Seconds per trial before skipping
TOTAL_TIMEOUT = 600  # 10 minutes max for all trials


def main() -> None:
    # Reset HTTP session to ensure fresh timeout settings
    reset_session()

    config = load_config()
    config = deduplicate_config(config)
    targets = config.get("targets", [])

    if not targets:
        print("No targets found in trials.yaml")
        return

    if not os.path.exists("data/snapshots"):
        os.makedirs("data/snapshots", exist_ok=True)

    # 1. Deduplicate trials across all targets to avoid redundant processing
    unique_trials = {}  # trial_id -> (trial_config, first_target_name)
    for target in targets:
        target_name = target["name"]
        for trial in target.get("trials", []):
            trial_id = trial["id"]
            if trial_id not in unique_trials:
                unique_trials[trial_id] = (trial, target_name)

    total_unique = len(unique_trials)
    print(f"Found {total_unique} unique trials across {len(targets)} targets.")

    # 2. Process unique trials in parallel using a single global executor
    processed_results = {}  # trial_id -> (report_item, raw_data)
    current_idx = 0

    # Pre-calculate 30-day threshold for efficient date checking in workers
    thirty_days_ago_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {
            executor.submit(process_trial, trial, tname, thirty_days_ago_str): tid
            for tid, (trial, tname) in unique_trials.items()
        }

        try:
            for future in as_completed(future_to_id, timeout=TOTAL_TIMEOUT):
                current_idx += 1
                trial_id = future_to_id[future]
                try:
                    report, raw = future.result(timeout=PER_TRIAL_TIMEOUT)
                    if report and raw:
                        processed_results[trial_id] = (report, raw)
                    print(f"[{current_idx}/{total_unique}] Processed {trial_id}")
                except TimeoutError:
                    print(
                        f"[{current_idx}/{total_unique}] Timeout processing {trial_id}"
                    )
                except Exception as e:
                    print(
                        f"[{current_idx}/{total_unique}] Error processing {trial_id}: {e}"
                    )
        except TimeoutError:
            print(f"  ⚠ Processing timed out after {TOTAL_TIMEOUT}s")

    # 3. Distribute results back to targets and save
    target_summaries = []
    total_processed_entries = 0

    for target in targets:
        target_name = target["name"]
        trials = target.get("trials", [])

        target_reports = []
        target_raw = []

        for trial_config in trials:
            tid = trial_config["id"]
            if tid in processed_results:
                base_report, base_raw = processed_results[tid]

                # Create copies to avoid side effects between targets
                report = base_report.copy()
                raw = base_raw.copy()

                # Customize for this specific target
                report["target"] = target_name
                report["name"] = trial_config.get("name", report["name"])
                raw["_target"] = target_name

                target_reports.append(report)
                target_raw.append(raw)
                total_processed_entries += 1

        # Save target-specific data
        if target_reports:
            try:
                save_target_data(target_name, target_reports, target_raw)
                update_target_history(target_name, target_reports)
            except Exception as e:
                print(f"  Error saving data for target {target_name}: {e}")

        # Collect target summary
        target_summaries.append(
            {
                "name": target_name,
                "description": target.get("description", ""),
                "trial_count": len(trials),
                "changed_count": sum(
                    1 for r in target_reports if r["monitor_status"] == "Changed"
                ),
            }
        )

    # Save global target summary
    with open("data/targets_summary.json", "w", encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(target_summaries, f, ensure_ascii=False)

    print(
        f"\n✓ Processed {len(targets)} targets, {total_processed_entries} total trial entries"
    )

    # Automatically update target pages and _quarto.yml
    print("\nUpdating website pages...")
    generate_pages()


if __name__ == "__main__":
    main()
    # Force exit to kill any lingering background threads from timed-out targets
    os._exit(0)
