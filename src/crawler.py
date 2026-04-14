import json
import os
import time
import random
from typing import Any, Dict, Optional
from utils import sanitize_id, is_valid_nct_id

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


def reset_session() -> None:
    """Reset the cached session (e.g. to apply new settings)."""
    global _session
    _session = None


def get_session() -> Optional[Any]:
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
        # Increase pool size to match MAX_WORKERS in main.py for better concurrency
        adapter = HTTPAdapter(
            max_retries=retry_strategy, pool_connections=20, pool_maxsize=20
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)

        # User-Agent is good practice to avoid being flagged as a generic bot
        _session.headers.update(
            {
                "User-Agent": "ClinicalTrialWatch/1.0 (https://github.com/partrita/clinicaltrial-watch)",
                "Accept": "application/json",
            }
        )
    return _session


def fetch_trial_data(trial_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches clinical trial data from ClinicalTrials.gov API v2.
    Uses connection pooling and retries for speed and reliability.
    """
    # Security enhancement: Validate NCT ID format
    if not is_valid_nct_id(trial_id):
        print(f"Error: Invalid NCT ID format: {trial_id}")
        return None

    # Sanitize trial_id to prevent injection and traversal
    safe_trial_id = sanitize_id(trial_id)
    url = f"https://clinicaltrials.gov/api/v2/studies/{safe_trial_id}"

    # Max response size: 10MB (to prevent memory exhaustion DoS)
    MAX_RESPONSE_SIZE = 10 * 1024 * 1024

    if HAS_REQUESTS:
        session = get_session()
        try:
            # Adding a tiny random jitter to avoid perfectly synchronized requests
            time.sleep(random.uniform(0.05, 0.1))

            # Use stream=True to check Content-Length before downloading full body
            response = session.get(url, timeout=(3, 15), stream=True)
            if response.status_code == 200:
                # Check Content-Length header if present
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                    print(f"Error: Response too large for {safe_trial_id}: {content_length} bytes")
                    response.close()
                    return None

                # Read in chunks to enforce limit even if header is missing/wrong
                content = []
                size = 0
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    size += len(chunk)
                    if size > MAX_RESPONSE_SIZE:
                        print(f"Error: Response exceeded size limit for {safe_trial_id}")
                        response.close()
                        return None
                    content.append(chunk)

                return json.loads(b"".join(content).decode("utf-8"))
            elif response.status_code == 404:
                print(f"Trial {safe_trial_id} not found (404).")
                return None
            else:
                print(
                    f"Error fetching data for {safe_trial_id}: {response.status_code}"
                )
                return None
        except Exception as e:
            print(f"Exception fetching data for {safe_trial_id}: {e}")
            # Reset session on connection errors to avoid stuck connections
            reset_session()
            return None
    else:
        # Fallback to urllib if requests is not available
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "ClinicalTrialWatch/1.0")
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    # Check Content-Length for urllib
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                        print(f"Error: Response too large for {safe_trial_id}")
                        return None

                    content = []
                    size = 0
                    while True:
                        chunk = response.read(128 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(f"Error: Response exceeded size limit for {safe_trial_id}")
                            return None
                        content.append(chunk)

                    return json.loads(b"".join(content).decode("utf-8"))
                else:
                    print(
                        f"Error fetching data for {safe_trial_id} (urllib): {response.status}"
                    )
                    return None
        except Exception as e:
            print(f"Exception fetching data for {safe_trial_id} (urllib): {e}")
            return None


def save_snapshot(
    trial_id: str, data: Dict[str, Any], snapshot_dir: str = "data/snapshots"
) -> str:
    """
    Saves the fetched data as a JSON snapshot.
    """
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir, exist_ok=True)

    # Sanitize trial_id to prevent path traversal
    safe_trial_id = sanitize_id(trial_id)
    filepath = os.path.join(snapshot_dir, f"{safe_trial_id}_latest.json")

    with open(filepath, "w", encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(data, f, ensure_ascii=False)
    return filepath
