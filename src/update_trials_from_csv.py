import csv
import os

def csv_to_yaml(csv_path, yaml_path):
    """
    Reads a CSV with 'NCT Number' and 'Study Title' and generates a trials.yaml file.
    """
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

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
        return

    if not trials:
        print("No valid trials found in CSV.")
        return

    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write("trials:\n")
            for trial in trials:
                # Basic escaping for single quotes in name
                name = trial['name'].replace("'", "''")
                f.write(f"  - id: '{trial['id']}'\n")
                f.write(f"    name: '{name}'\n")
        print(f"Successfully updated {yaml_path} with {len(trials)} trials.")
    except Exception as e:
        print(f"Error writing YAML: {e}")

if __name__ == "__main__":
    CSV_FILE = "data/ctg-studies.csv"
    YAML_FILE = "trials.yaml"
    csv_to_yaml(CSV_FILE, YAML_FILE)
