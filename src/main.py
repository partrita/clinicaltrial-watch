#!/usr/bin/env python3
"""
Main script for clinical trial monitoring.
Fetches trial data, compares with previous snapshots, and generates target-based reports.
"""

import os
import json
import csv
from datetime import datetime
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
                
                if stripped.startswith("- name:") and indent == 2:
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
                elif stripped.startswith("name:") and current_trial and indent >= 8:
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


def update_history(trial_id, diff_text, history_dir="data/history"):
    """Save change history for a trial."""
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_file = os.path.join(history_dir, f"{trial_id}_history.json")
    
    history = []
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    
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
    
    history = []
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    
    # Check for changes
    changed_trials = [r['id'] for r in current_reports if r['monitor_status'] == "Changed"]
    
    message = ""
    if not history:
        message = f"Initial data collection: {len(current_reports)} trials found."
    elif changed_trials:
        message = f"Changes detected in {len(changed_trials)} trials: {', '.join(changed_trials)}"
    
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
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
        else:
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
            "monitor_status": "Changed",
            "last_monitored_change": last_monitored,
            "details": f"**[CHANGES FOUND]**\n{diff_text}\n\n---\n{detailed_desc}"
        })
    else:
        history_file = f"data/history/{trial_id}_history.json"
        if not os.path.exists(history_file):
            print(f"  Initializing history for {trial_id}")
            update_history(trial_id, "Initial data collection")
            
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if history:
                    report_item["last_monitored_change"] = history[-1]['timestamp'].split(' ')[0]
    
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


def main():
    config = load_config()
    targets = config.get('targets', [])
    
    if not targets:
        print("No targets found in trials.yaml")
        return
    
    if not os.path.exists("data/snapshots"):
        os.makedirs("data/snapshots")
    
    # Process each target
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
        
        for trial in trials:
            current_trial_idx += 1
            print(f"[{current_trial_idx}/{total_trials}]", end=" ")
            report, raw = process_trial(trial, target_name)
            if report:
                target_reports.append(report)
                all_reports.append(report)
            if raw:
                target_raw.append(raw)
                all_raw.append(raw)
        
        # Save target-specific data
        if target_reports:
            save_target_data(target_name, target_reports, target_raw)
            update_target_history(target_name, target_reports)
        
        # Collect target summary
        target_summaries.append({
            "name": target_name,
            "description": target.get('description', ''),
            "trial_count": len(target_reports),
            "changed_count": sum(1 for r in target_reports if r['monitor_status'] == 'Changed')
        })
    
    # Save global target summary for index page
    with open("data/targets_summary.json", 'w', encoding='utf-8') as f:
        json.dump(target_summaries, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Processed {len(targets)} targets, {len(all_reports)} total trials")
    
    # Automatically update target pages and _quarto.yml
    print("\nUpdating website pages...")
    generate_pages()


if __name__ == "__main__":
    main()
