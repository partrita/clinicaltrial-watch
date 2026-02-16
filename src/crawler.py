import json
import os
import time
import random

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    HAS_REQUESTS = False

# Global session to reuse connections (much faster)
_session = None

def reset_session():
    """Reset the cached session (e.g. to apply new settings)."""
    global _session
    _session = None

def get_session():
    """Returns a requests session with retry logic and custom headers."""
    global _session
    if not HAS_REQUESTS:
        return None
        
    if _session is None:
        _session = requests.Session()
        # ClinicalTrials.gov API v2 is generally fast, but retries help with transient issues
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
        
        # User-Agent is good practice to avoid being flagged as a generic bot
        _session.headers.update({
            "User-Agent": "ClinicalTrialWatch/1.0 (https://github.com/partrita/clinicaltrial-watch)",
            "Accept": "application/json"
        })
    return _session

def fetch_trial_data(trial_id):
    """
    Fetches clinical trial data from ClinicalTrials.gov API v2.
    Uses connection pooling and retries for speed and reliability.
    """
    url = f"https://clinicaltrials.gov/api/v2/studies/{trial_id}"
    
    if HAS_REQUESTS:
        session = get_session()
        try:
            # Adding a tiny random jitter to avoid perfectly synchronized requests
            # which can sometimes trigger bot protection
            time.sleep(random.uniform(0.05, 0.1))
            
            response = session.get(url, timeout=(3, 5))  # (connect, read) timeout
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                print(f"Trial {trial_id} not found (404).")
                return None
            else:
                print(f"Error fetching data for {trial_id}: {response.status_code}")
                return None
        except Exception as e:
            print(f"Exception fetching data for {trial_id}: {e}")
            # Reset session on connection errors to avoid stuck connections
            reset_session()
            return None
    else:
        # Fallback to urllib if requests is not available
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "ClinicalTrialWatch/1.0")
            with urllib.request.urlopen(req, timeout=10) as response:
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
        os.makedirs(snapshot_dir, exist_ok=True)
    
    filepath = os.path.join(snapshot_dir, f"{trial_id}_latest.json")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return filepath
