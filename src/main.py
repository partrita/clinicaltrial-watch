import os
import json
import csv
from datetime import datetime
from crawler import fetch_trial_data, save_snapshot
from diff_engine import compare_snapshots, format_diff

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

def load_config(config_path="trials.yaml"):
    if HAS_YAML:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    else:
        # Fallback manual parser for the simple trials.yaml structure
        print("Warning: 'yaml' module not found. Using simple manual parser.")
        trials = []
        current_trial = {}
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if line.startswith("- id:"):
                    if current_trial: trials.append(current_trial)
                    current_trial = {'id': line.split(":", 1)[1].strip().strip('"').strip("'")}
                elif line.startswith("name:"):
                    if 'id' in current_trial:
                        current_trial['name'] = line.split(":", 1)[1].strip().strip('"').strip("'")
            if current_trial: trials.append(current_trial)
        return {'trials': trials}

def update_history(trial_id, diff_text, history_dir="data/history"):
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

def flatten_dict(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        # Shorten prefixes for readability
        clean_k = k
        if parent_key == '':
            if k == 'protocolSection': clean_k = 'Prot'
            elif k == 'derivedSection': clean_k = 'Deriv'
            elif k == 'annotationSection': clean_k = 'Annot'
            elif k == 'resultsSection': clean_k = 'Res'
        
        # Specific sub-module shortening
        if k.endswith('Module'): clean_k = k.replace('Module', '')
        if k.endswith('Struct'): clean_k = k.replace('Struct', '')
        
        new_key = f"{parent_key}{sep}{clean_k}" if parent_key else clean_k
        
        # Final cleanup of common long prefixes
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

def main():
    config = load_config()
    trials = config.get('trials', [])
    
    summary_report = []
    all_raw_data = []

    if not os.path.exists("data/snapshots"):
        os.makedirs("data/snapshots")

    for trial in trials:
        trial_id = trial['id']
        print(f"Processing {trial_id}...")
        
        new_data = fetch_trial_data(trial_id)
        if not new_data:
            # Try to load from local if fetch fails
            local_path = f"data/snapshots/{trial_id}_latest.json"
            if os.path.exists(local_path):
                with open(local_path, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
            else:
                print(f"Skipping {trial_id} - no data available.")
                continue

        # Collect raw data for flattening
        all_raw_data.append(flatten_dict(new_data))
            
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
        detailed_desc = protocol.get('descriptionModule', {}).get('detailedDescription', protocol.get('descriptionModule', {}).get('briefSummary', 'N/A'))

        diff = compare_snapshots(trial_id, new_data)
        
        report_item = {
            "id": trial_id,
            "name": trial['name'],
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
            print(f"Changes found for {trial_id}:\n{diff_text}")
            update_history(trial_id, diff_text)
            last_monitored = datetime.now().strftime("%Y-%m-%d")
            report_item.update({
                "monitor_status": "Changed",
                "last_monitored_change": last_monitored,
                "details": f"**[CHANGES FOUND]**\n{diff_text}\n\n---\n{detailed_desc}"
            })
        else:
            history_file = f"data/history/{trial_id}_history.json"
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    if history:
                        report_item["last_monitored_change"] = history[-1]['timestamp'].split(' ')[0]

            print(f"No changes for {trial_id}.")
        
        summary_report.append(report_item)
        save_snapshot(trial_id, new_data)

    with open("data/status_summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary_report, f, indent=2, ensure_ascii=False)

    if summary_report:
        keys = summary_report[0].keys()
        with open("data/status_summary.csv", 'w', encoding='utf-8-sig', newline='') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(summary_report)
        print("Summary saved to data/status_summary.csv")

    # Save all raw data as a single CSV
    if all_raw_data:
        all_keys = set()
        for row in all_raw_data:
            all_keys.update(row.keys())
        
        headers = sorted(list(all_keys))
        with open("data/all_trials_raw.csv", 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(all_raw_data)
        print(f"Consolidated raw data saved to data/all_trials_raw.csv")

if __name__ == "__main__":
    main()
