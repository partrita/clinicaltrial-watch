import json
import os

try:
    from deepdiff import DeepDiff
    HAS_DEEPDIFF = True
except ImportError:
    HAS_DEEPDIFF = False

def compare_snapshots(trial_id, new_data, snapshot_dir="data/snapshots"):
    """
    Compares the new data with the previous snapshot of the trial using DeepDiff.
    """
    previous_path = os.path.join(snapshot_dir, f"{trial_id}_latest.json")
    
    if not os.path.exists(previous_path):
        return None  # No previous data to compare with

    try:
        with open(previous_path, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
    except Exception as e:
        print(f"  Warning: Failed to load previous snapshot for {trial_id}: {e}")
        return None

    # Focus on protocolSection for substantive changes
    old_protocol = old_data.get('protocolSection', {})
    new_protocol = new_data.get('protocolSection', {})

    if HAS_DEEPDIFF:
        diff = DeepDiff(old_protocol, new_protocol, ignore_order=True)
        return diff
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

def format_diff(diff):
    """
    Converts diff object into a human-readable summary.
    """
    if not diff:
        return ""
    
    if not HAS_DEEPDIFF:
        # Format the simple fallback diff
        lines = []
        for label, change in diff.items():
            lines.append(f"{label}: `{change['old']}` -> `{change['new']}`")
        return "\n".join(lines)
    
    summary = []
    # Values changed
    if 'values_changed' in diff:
        for path, change in diff['values_changed'].items():
            # Clean up path for readability (e.g. root['statusModule']['overallStatus'])
            clean_path = path.replace("root", "").replace("['", "").replace("']", ".").strip(".")
            summary.append(f"Field `{clean_path}` changed from `{change['old_value']}` to `{change['new_value']}`")
    
    # Dictionary items added/removed
    if 'dictionary_item_added' in diff:
        for path in diff['dictionary_item_added']:
            summary.append(f"New field added: `{path}`")

    if 'dictionary_item_removed' in diff:
        for path in diff['dictionary_item_removed']:
            summary.append(f"Field removed: `{path}`")

    return "\n".join(summary) if summary else "Minor formatting updates."
