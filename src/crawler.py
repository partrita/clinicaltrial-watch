import json
import os

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    HAS_REQUESTS = False

def fetch_trial_data(trial_id):
    """
    Fetches clinical trial data from ClinicalTrials.gov API v2.
    """
    url = f"https://clinicaltrials.gov/api/v2/studies/{trial_id}"
    if HAS_REQUESTS:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching data for {trial_id}: {response.status_code}")
                return None
        except Exception as e:
            print(f"Exception fetching data for {trial_id} (requests): {e}")
            return None
    else:
        try:
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
                else:
                    print(f"Error fetching data for {trial_id} (urllib): {response.status}")
                    return None
        except Exception as e:
            print(f"Exception fetching data for {trial_id} (urllib): {e}")
            return None

def save_snapshot(trial_id, data, snapshot_dir="data/snapshots"):
    """
    Saves the fetched data as a JSON snapshot.
    """
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir)
    
    filepath = os.path.join(snapshot_dir, f"{trial_id}_latest.json")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return filepath
