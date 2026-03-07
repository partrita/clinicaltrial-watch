#!/usr/bin/env python3
"""
Auto-discover new clinical trials from ClinicalTrials.gov based on targets in trials.yaml.
Queries the API for each target and appends new trials to trials.yaml.
"""

import time
import random
from typing import Any, Dict, List, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import json

    HAS_REQUESTS = False

from update_trials_from_csv import load_yaml, save_yaml, update_target

_session = None


def get_session() -> Optional[Any]:
    global _session
    if not HAS_REQUESTS:
        return None

    if _session is None:
        _session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)

        _session.headers.update(
            {
                "User-Agent": "ClinicalTrialWatch/AutoDiscover/1.0",
                "Accept": "application/json",
            }
        )
    return _session


def search_trials(query_term: str) -> List[Dict[str, Any]]:
    """Search ClinicalTrials.gov API for a given term."""
    # Searching with max 1000 items (maximum allowed by pageSize)
    # If there are more than 1000, we might need pagination, but it's unlikely for specific targets
    url = f"https://clinicaltrials.gov/api/v2/studies?query.term={query_term}&pageSize=1000"

    if HAS_REQUESTS:
        session = get_session()
        try:
            time.sleep(random.uniform(0.5, 1.0))  # Be polite to API
            response = session.get(url, timeout=(5, 15))
            if response.status_code == 200:
                data = response.json()
                return data.get("studies", [])
            else:
                print(
                    f"Error fetching data for term {query_term}: {response.status_code}"
                )
                return []
        except Exception as e:
            print(f"Exception fetching data for term {query_term}: {e}")
            global _session
            _session = None
            return []
    else:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "ClinicalTrialWatch/AutoDiscover/1.0")
            time.sleep(random.uniform(0.5, 1.0))
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return data.get("studies", [])
                else:
                    print(
                        f"Error fetching data for term {query_term} (urllib): {response.status}"
                    )
                    return []
        except Exception as e:
            print(f"Exception fetching data for term {query_term} (urllib): {e}")
            return []


def extract_trials(api_studies: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Extract required trial info from API response."""
    trials = []
    for study in api_studies:
        try:
            protocol = study.get("protocolSection", {})
            identity = protocol.get("identificationModule", {})
            nct_id = identity.get("nctId")
            title = identity.get("briefTitle")
            if nct_id and title:
                trials.append({"id": nct_id, "name": title})
        except Exception as e:
            print(f"Error extracting study data: {e}")
    return trials


def main() -> int:
    yaml_path = "trials.yaml"

    print("Loading existing trials...")
    data = load_yaml(yaml_path)

    targets = data.get("targets", [])
    if not targets:
        print("No targets found in trials.yaml. Nothing to auto-discover.")
        return 0

    total_added = 0

    for target in targets:
        target_name = target["name"]
        print(f"\nSearching for '{target_name}' on ClinicalTrials.gov...")

        api_studies = search_trials(target_name)
        if not api_studies:
            print(f"No studies found or error occurred for '{target_name}'.")
            continue

        new_trials = extract_trials(api_studies)
        print(f"Found {len(new_trials)} studies related to '{target_name}' via API.")

        # Determine existing trials for this target to count exactly how many are new
        existing_target = next(
            (t for t in targets if t["name"].lower() == target_name.lower()), None
        )
        existing_ids = (
            {t["id"] for t in existing_target.get("trials", [])}
            if existing_target
            else set()
        )

        # Perform the update
        data = update_target(data, target_name, new_trials, target.get("description"))

        # Refresh the target block to see how many were actually added
        updated_target = next(
            (t for t in data["targets"] if t["name"].lower() == target_name.lower()),
            None,
        )
        updated_ids = (
            {t["id"] for t in updated_target.get("trials", [])}
            if updated_target
            else set()
        )

        added_count = len(updated_ids) - len(existing_ids)
        total_added += added_count

        if added_count > 0:
            print(f"-> Added {added_count} brand new trials to '{target_name}'.")
        else:
            print(f"-> No new trials to add for '{target_name}'.")

    if total_added > 0:
        print(
            f"\nSuccessfully discovered and added {total_added} total new trials across all targets."
        )
        save_yaml(data, yaml_path)
    else:
        print(
            "\nNo new trials discovered across any targets. No changes made to trials.yaml."
        )

    return 0


if __name__ == "__main__":
    exit(main())
