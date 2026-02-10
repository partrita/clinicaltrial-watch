#!/usr/bin/env python3
"""
Update trials.yaml by adding trials from a CSV file to a specific target.
Usage: python update_trials_from_csv.py --target CCR8 --csv data/ctg-studies.csv
"""

import argparse
import csv
import os

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def load_yaml(yaml_path):
    """Load existing YAML file or return empty structure."""
    if not os.path.exists(yaml_path):
        return {'targets': []}
    
    if HAS_YAML:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    else:
        # Simple fallback parser
        data = {'targets': []}
        print("Warning: 'yaml' module not found. Creating new structure.")
    
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
    
    if 'targets' not in data:
        data['targets'] = []
    
    return data


def save_yaml(data, yaml_path):
    """Save YAML data to file."""
    if HAS_YAML:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        # Manual YAML writer
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write("targets:\n")
            for target in data.get('targets', []):
                f.write(f"  - name: {target['name']}\n")
                f.write(f"    description: \"{target.get('description', '')}\"\n")
                f.write("    trials:\n")
                for trial in target.get('trials', []):
                    name = trial['name'].replace("'", "''")
                    f.write(f"      - id: '{trial['id']}'\n")
                    f.write(f"        name: '{name}'\n")
    print(f"Saved to {yaml_path}")


def read_csv_trials(csv_path):
    """Read trials from CSV file."""
    trials = []
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nct_id = row.get('NCT Number', '').strip()
                title = row.get('Study Title', '').strip()
                if nct_id and title:
                    trials.append({'id': nct_id, 'name': title})
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return trials


def update_target(data, target_name, new_trials, description=None):
    """Update or create a target with new trials."""
    # Find existing target
    target = None
    for t in data['targets']:
        if t['name'].lower() == target_name.lower():
            target = t
            break
    
    # Create new target if not found
    if target is None:
        target = {
            'name': target_name,
            'description': description or f"{target_name} 타겟 임상시험 모니터링",
            'trials': []
        }
        data['targets'].append(target)
    
    # Get existing trial IDs
    existing_ids = {trial['id'] for trial in target.get('trials', [])}
    
    # Add new trials
    added = 0
    for trial in new_trials:
        if trial['id'] not in existing_ids:
            target['trials'].append(trial)
            existing_ids.add(trial['id'])
            added += 1
    
    print(f"Target '{target_name}': {added} new trials added, {len(target['trials'])} total")
    return data


def main():
    parser = argparse.ArgumentParser(description='Update trials.yaml with trials from CSV')
    parser.add_argument('--target', '-t', required=True, help='Target name (e.g., CCR8, TIGIT)')
    parser.add_argument('--csv', '-c', default='data/ctg-studies.csv', help='Path to CSV file')
    parser.add_argument('--yaml', '-y', default='trials.yaml', help='Path to trials.yaml')
    parser.add_argument('--description', '-d', help='Target description (for new targets)')
    parser.add_argument('--replace', action='store_true', help='Replace existing trials instead of adding')
    
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
        for target in data['targets']:
            if target['name'].lower() == args.target.lower():
                target['trials'] = []
                break
    
    # Update target
    data = update_target(data, args.target, new_trials, args.description)
    
    # Save
    save_yaml(data, args.yaml)
    return 0


if __name__ == "__main__":
    exit(main())
