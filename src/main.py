#!/usr/bin/env python3
"""
Main script for clinical trial monitoring.
Fetches trial data, compares with previous snapshots, and generates target-based reports.
"""

import os
import json
import csv
from datetime import datetime, timedelta
from crawler import fetch_trial_data, save_snapshot
from diff_engine import compare_snapshots, format_diff
from generate_target_pages import main as generate_pages

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def load_config(config_path="trials.yaml"):
    """Load trials configuration from YAML file."""
    data = {}
    if HAS_YAML:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    else:
        # Fallback manual parser for targets structure
        print("Warning: 'yaml' module not found. Using simple manual parser.")
        targets = []
        current_target = None
        current_trial = {}
        
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                
                indent = len(line) - len(line.lstrip())
                
                if stripped.startswith("- name:"):
                    if current_target:
                        targets.append(current_target)
                    current_target = {
                        'name': stripped.split(":", 1)[1].strip().strip('"').strip("'"),
                        'description': '',
                        'trials': []
                    }
                elif stripped.startswith("description:") and current_target:
                    current_target['description'] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                elif stripped.startswith("- id:") and current_target:
                    if current_trial:
                        current_target['trials'].append(current_trial)
                    current_trial = {'id': stripped.split(":", 1)[1].strip().strip('"').strip("'")}
                elif stripped.startswith("name:") and current_trial:
                    current_trial['name'] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            
            if current_trial and current_target:
                current_target['trials'].append(current_trial)
            if current_target:
                targets.append(current_target)
        
        data = {'targets': targets}

    # Handle legacy format (flat trials list)
    if 'trials' in data and 'targets' not in data:
        print("Converting legacy format to target-based structure...")
        data = {
            'targets': [{
                'name': 'Default',
                'description': 'Migrated from legacy format',
                'trials': data['trials']
            }]
        }
    
    # Handle old 'topics' naming
    if 'topics' in data and 'targets' not in data:
        data['targets'] = data.pop('topics')
    
    return data


_SENTINEL = object()

def safe_json_load(file_path, default=_SENTINEL):
    """Safely load JSON from a file, returning default if error occurs."""
    if default is _SENTINEL:
        default = []
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  Warning: Failed to load {file_path}: {e}. Returning default.")
        return default


def update_history(trial_id, diff_text, history_dir="data/history"):
    """Save change history for a trial."""
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_file = os.path.join(history_dir, f"{trial_id}_history.json")
    
    history = safe_json_load(history_file, default=[])
    
    history.append({
        "timestamp": timestamp,
        "diff": diff_text
    })
    
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_target_history(target_name, current_reports, history_dir="data/history"):
    """Save change history for a target."""
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_file = os.path.join(history_dir, f"target_{target_name.lower()}.json")
    
    history = safe_json_load(history_file, default=[])
    
    # Check for changes today specifically for the daily log
    changed_today = [r['id'] for r in current_reports if r.get('changed_today')]
    
    message = ""
    if not history:
        message = f"Initial data collection: {len(current_reports)} trials found."
    elif changed_today:
        message = f"Changes detected in {len(changed_today)} trials: {', '.join(changed_today)}"
    
    if message:
        history.append({
            "timestamp": timestamp,
            "event": message
        })
        
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"  Updated target history for {target_name}")


def flatten_dict(d, parent_key='', sep='_'):
    """Flatten nested dictionary for CSV export."""
    items = []
    for k, v in d.items():
        clean_k = k
        if parent_key == '':
            if k == 'protocolSection': clean_k = 'Prot'
            elif k == 'derivedSection': clean_k = 'Deriv'
            elif k == 'annotationSection': clean_k = 'Annot'
            elif k == 'resultsSection': clean_k = 'Res'
        
        if k.endswith('Module'): clean_k = k.replace('Module', '')
        if k.endswith('Struct'): clean_k = k.replace('Struct', '')
        
        new_key = f"{parent_key}{sep}{clean_k}" if parent_key else clean_k
        
        for prefix in ['Prot_', 'Deriv_', 'Annot_', 'Res_']:
            if new_key.startswith(prefix):
                new_key = new_key[len(prefix):]

        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            if all(isinstance(i, (str, int, float, bool)) for i in v):
                items.append((new_key, ", ".join(map(str, v))))
            else:
                items.append((new_key, json.dumps(v, ensure_ascii=False)))
        else:
            items.append((new_key, v))
    return dict(items)


def process_trial(trial, target_name):
    """Process a single trial and return report data."""
    trial_id = trial['id']
    print(f"Processing {trial_id}...")
    
    new_data = fetch_trial_data(trial_id)
    if not new_data:
        local_path = f"data/snapshots/{trial_id}_latest.json"
        new_data = safe_json_load(local_path, default=None)
        if not new_data:
            print(f"  Skipping {trial_id} - no data available.")
            return None, None
    
    raw_data = flatten_dict(new_data)
    raw_data['_target'] = target_name
    
    protocol = new_data.get('protocolSection', {})
    status_mod = protocol.get('statusModule', {})
    
    sponsor = protocol.get('sponsorCollaboratorsModule', {}).get('leadSponsor', {}).get('name', 'N/A')
    last_update = status_mod.get('lastUpdatePostDateStruct', {}).get('date', 'N/A')
    start_date = status_mod.get('startDateStruct', {}).get('date', 'N/A')
    end_date = status_mod.get('completionDateStruct', {}).get('date', 'N/A')
    enrollment = protocol.get('designModule', {}).get('enrollmentInfo', {}).get('count', 'N/A')
    
    primary_outcomes = protocol.get('outcomesModule', {}).get('primaryOutcomes', [])
    primary_outcome = primary_outcomes[0].get('measure', 'N/A') if primary_outcomes else 'N/A'
    
    study_status = status_mod.get('overallStatus', 'N/A')
    last_submit_date = status_mod.get('lastUpdateSubmitDate', 'N/A')
    conditions_list = protocol.get('conditionsModule', {}).get('conditions', [])
    conditions = ", ".join(conditions_list) if conditions_list else "N/A"
    phases_list = protocol.get('designModule', {}).get('phases', [])
    phases = ", ".join(phases_list) if phases_list else "N/A"
    detailed_desc = protocol.get('descriptionModule', {}).get('detailedDescription', 
                    protocol.get('descriptionModule', {}).get('briefSummary', 'N/A'))

    diff = compare_snapshots(trial_id, new_data)
    
    report_item = {
        "id": trial_id,
        "name": trial['name'],
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
        "details": detailed_desc
    }

    if diff:
        diff_text = format_diff(diff)
        print(f"  Changes found for {trial_id}")
        update_history(trial_id, diff_text)
        last_monitored = datetime.now().strftime("%Y-%m-%d")
        report_item.update({
            "changed_today": True,
            "last_monitored_change": last_monitored,
            "details": f"**[RECENT CHANGES FOUND]**\n{diff_text}\n\n***\n{detailed_desc}"
        })
    else:
        history_file = f"data/history/{trial_id}_history.json"
        if not os.path.exists(history_file):
            print(f"  Initializing history for {trial_id}")
            update_history(trial_id, "Initial data collection")
            
    # Check for any changes in the last 30 days to set monitor_status
    history_file = f"data/history/{trial_id}_history.json"
    history = safe_json_load(history_file, default=[])
    if history:
        # Update last_monitored_change from history
        report_item["last_monitored_change"] = history[-1]['timestamp'].split(' ')[0]
                
        # Check 30 day window
        thirty_days_ago = datetime.now() - timedelta(days=30)
        for record in reversed(history): # Search from newest
            if record['diff'] == "Initial data collection":
                continue
            try:
                ts = record['timestamp']
                if len(ts) > 10:
                    record_date = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                else:
                    record_date = datetime.strptime(ts, "%Y-%m-%d")
                    
                if record_date > thirty_days_ago:
                    report_item["monitor_status"] = "Changed"
                    break
            except Exception:
                continue
    
    save_snapshot(trial_id, new_data)
    return report_item, raw_data


def save_target_data(target_name, summary_report, all_raw_data):
    """Save data for a specific target."""
    target_dir = f"data/targets/{target_name.lower()}"
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    
    # Save JSON summary
    with open(f"{target_dir}/status_summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary_report, f, indent=2, ensure_ascii=False)
    
    # Save CSV summary
    if summary_report:
        keys = set()
        for item in summary_report:
            keys.update(item.keys())
        headers = sorted(list(keys))
        
        with open(f"{target_dir}/status_summary.csv", 'w', encoding='utf-8-sig', newline='') as f:
            dict_writer = csv.DictWriter(f, fieldnames=headers)
            dict_writer.writeheader()
            dict_writer.writerows(summary_report)
    
    # Save raw data CSV
    if all_raw_data:
        all_keys = set()
        for row in all_raw_data:
            all_keys.update(row.keys())
        
        headers = sorted(list(all_keys))
        with open(f"{target_dir}/all_trials_raw.csv", 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(all_raw_data)
    
    print(f"  Saved target data to {target_dir}/")


from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from crawler import reset_session

MAX_WORKERS = 10  # Reasonable number of concurrent requests to avoid getting blocked
PER_TRIAL_TIMEOUT = 30  # Seconds per trial before skipping
TARGET_TIMEOUT = 120  # 2 minutes max per target

def main():
    # Reset HTTP session to ensure fresh timeout settings
    reset_session()
    
    config = load_config()
    targets = config.get('targets', [])
    
    if not targets:
        print("No targets found in trials.yaml")
        return
    
    if not os.path.exists("data/snapshots"):
        os.makedirs("data/snapshots", exist_ok=True)
    
    # Collect all trials for batch processing if needed, but here we process target by target
    target_summaries = []
    all_reports = []
    all_raw = []
    
    total_trials = sum(len(target.get('trials', [])) for target in targets)
    current_trial_idx = 0
    
    for target in targets:
        target_name = target['name']
        trials = target.get('trials', [])
        
        print(f"\nProcessing target: {target_name} ({len(trials)} trials)")
        
        target_reports = []
        target_raw = []
        
        # Parallel processing of trials within each target
        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        future_to_trial = {
            executor.submit(process_trial, trial, target_name): trial 
            for trial in trials
        }
        
        try:
            for future in as_completed(future_to_trial, timeout=TARGET_TIMEOUT):
                current_trial_idx += 1
                try:
                    report, raw = future.result(timeout=PER_TRIAL_TIMEOUT)
                    if report:
                        target_reports.append(report)
                        all_reports.append(report)
                    if raw:
                        target_raw.append(raw)
                        all_raw.append(raw)
                    
                    print(f"[{current_trial_idx}/{total_trials}] Processed {future_to_trial[future]['id']}")
                except TimeoutError:
                    trial_id = future_to_trial[future]['id']
                    print(f"[{current_trial_idx}/{total_trials}] Timeout processing {trial_id}, skipping")
                except Exception as e:
                    trial_id = future_to_trial[future]['id']
                    print(f"[{current_trial_idx}/{total_trials}] Error processing {trial_id}: {e}")
        except TimeoutError:
            skipped = sum(1 for f in future_to_trial if not f.done())
            print(f"  ⚠ Target {target_name} timed out after {TARGET_TIMEOUT}s, skipped {skipped} remaining trials")
        finally:
            # Don't wait for remaining threads — move on immediately
            executor.shutdown(wait=False, cancel_futures=True)
        
        # Save target-specific data
        if target_reports:
            try:
                save_target_data(target_name, target_reports, target_raw)
                update_target_history(target_name, target_reports)
            except Exception as e:
                print(f"  Error saving data for target {target_name}: {e}")
        
        # Collect target summary
        target_summaries.append({
            "name": target_name,
            "description": target.get('description', ''),
            "trial_count": len(trials), # Use expected count from config
            "changed_count": sum(1 for r in target_reports if r['monitor_status'] == 'Changed')
        })
        
        # Save global target summary after each target for better visibility
        with open("data/targets_summary.json", 'w', encoding='utf-8') as f:
            json.dump(target_summaries, f, indent=2, ensure_ascii=False)
            
    print(f"\n✓ Processed {len(targets)} targets, {len(all_reports)} total trials")
    
    # Automatically update target pages and _quarto.yml
    print("\nUpdating website pages...")
    generate_pages()


if __name__ == "__main__":
    main()
    # Force exit to kill any lingering background threads from timed-out targets
    os._exit(0)
