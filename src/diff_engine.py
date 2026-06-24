import json
import os
from typing import Any, Dict, Optional

try:
    from deepdiff import DeepDiff

    HAS_DEEPDIFF = True
except ImportError:
    HAS_DEEPDIFF = False

try:
    from utils import sanitize_id, check_file_size, safe_str
except ImportError:
    from src.utils import sanitize_id, check_file_size, safe_str

# Security limits for diff formatting to prevent DoS (CWE-400)
MAX_CHANGES = 100
MAX_PATH_LEN = 255
MAX_DEPTH = 20


def compare_snapshots(
    trial_id: str, new_data: Dict[str, Any], snapshot_dir: str = "data/snapshots"
) -> Optional[Any]:
    """
    Compares the new data with the previous snapshot of the trial using DeepDiff.
    """
    # Sanitize trial_id to prevent path traversal
    safe_trial_id = sanitize_id(trial_id)
    previous_path = os.path.join(snapshot_dir, f"{safe_trial_id}_latest.json")

    if not os.path.exists(previous_path):
        return None  # No previous data to compare with

    # Security enhancement: Check file size before loading to prevent DoS (CWE-400)
    check_file_size(previous_path)

    try:
        with open(previous_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except Exception as e:
        print(f"  Warning: Failed to load previous snapshot for {trial_id}: {e}")
        return None

    if not isinstance(old_data, dict):
        print(f"  Warning: Previous snapshot for {trial_id} is not a dictionary.")
        return None

    # Focus on protocolSection for substantive changes
    old_protocol = old_data.get("protocolSection", {})
    new_protocol = new_data.get("protocolSection", {})

    # Fast-path: Check for equality before expensive DeepDiff
    if old_protocol == new_protocol:
        return None

    if HAS_DEEPDIFF:
        import sys

        old_limit = sys.getrecursionlimit()
        # Ensure recursion limit is at least enough for our MAX_DEPTH
        # + some margin for DeepDiff's own internal calls
        if old_limit < MAX_DEPTH + 100:
            sys.setrecursionlimit(MAX_DEPTH + 100)

        try:
            # We use exclude_obj_callback to simulate a depth limit since DeepDiff
            # doesn't have a native max_depth parameter.
            def depth_limit_callback(obj, path):
                # path looks like "root['level1']['level2']..."
                # Count occurrences of '[' to estimate depth
                return path.count("[") > MAX_DEPTH

            diff = DeepDiff(
                old_protocol,
                new_protocol,
                exclude_obj_callback=depth_limit_callback,
            )
            return diff
        finally:
            sys.setrecursionlimit(old_limit)
    else:
        # Simple fallback diff
        fields_to_watch = {
            "Status": ["statusModule", "overallStatus"],
            "Phase": ["designModule", "phases"],
            "Completion Date": ["statusModule", "completionDateStruct", "date"],
            "Sponsor": ["sponsorCollaboratorsModule", "leadSponsor", "name"],
            "Start Date": ["statusModule", "startDateStruct", "date"],
            "Enrollment": ["designModule", "enrollmentInfo", "count"],
        }
        fallback_diff = {}
        for label, path in fields_to_watch.items():
            ov, nv = old_protocol, new_protocol
            for key in path:
                ov = ov.get(key, {}) if isinstance(ov, dict) else {}
                nv = nv.get(key, {}) if isinstance(nv, dict) else {}
            if ov != nv:
                fallback_diff[label] = {"old": ov, "new": nv}
        return fallback_diff if fallback_diff else None


def format_diff(diff: Any) -> str:
    """
    Converts diff object into a human-readable summary.
    """
    if not diff:
        return ""

    truncated_msg = "... (additional changes truncated for brevity)"

    if not HAS_DEEPDIFF:
        # Format the simple fallback diff
        lines = []
        for label, change in diff.items():
            # Security enhancement: Limit number of changes to prevent DoS
            if len(lines) >= MAX_CHANGES:
                lines.append(truncated_msg)
                break
            # Security enhancement: Truncate large values to prevent DoS
            old_val = safe_str(change["old"], 1000)
            new_val = safe_str(change["new"], 1000)
            # Security enhancement: Truncate label/path
            safe_label = safe_str(label, MAX_PATH_LEN)
            lines.append(f"{safe_label}: `{old_val}` -> `{new_val}`")
        return "\n".join(lines)

    summary = []

    def check_limit():
        return len(summary) >= MAX_CHANGES

    # Values changed
    if "values_changed" in diff:
        for path, change in diff["values_changed"].items():
            if check_limit():
                break
            # Clean up path for readability (e.g. root['statusModule']['overallStatus'])
            clean_path = (
                path.replace("root", "").replace("['", "").replace("']", ".").strip(".")
            )
            # Security enhancement: Truncate path
            clean_path = safe_str(clean_path, MAX_PATH_LEN)
            # Security enhancement: Truncate large values to prevent DoS
            old_val = safe_str(change["old_value"], 1000)
            new_val = safe_str(change["new_value"], 1000)
            summary.append(
                f"Field `{clean_path}` changed from `{old_val}` to `{new_val}`"
            )

    # Dictionary items added/removed
    if "dictionary_item_added" in diff and not check_limit():
        for path in diff["dictionary_item_added"]:
            if check_limit():
                break
            # Security enhancement: Truncate path
            safe_path = safe_str(path, MAX_PATH_LEN)
            summary.append(f"New field added: `{safe_path}`")

    if "dictionary_item_removed" in diff and not check_limit():
        for path in diff["dictionary_item_removed"]:
            if check_limit():
                break
            # Security enhancement: Truncate path
            safe_path = safe_str(path, MAX_PATH_LEN)
            summary.append(f"Field removed: `{safe_path}`")

    if check_limit():
        summary.append(truncated_msg)

    return "\n".join(summary) if summary else "Minor formatting updates."
