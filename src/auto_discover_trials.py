#!/usr/bin/env python3
"""
Auto-discover new clinical trials from ClinicalTrials.gov based on targets in trials.yaml.
Queries the API for each target and appends new trials to trials.yaml.
"""

import time
import random
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from utils import is_valid_nct_id

import urllib.request
import urllib.parse
import json

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from update_trials_from_csv import load_yaml, save_yaml, update_target

_session = None
_session_lock = threading.Lock()


def get_session() -> Optional[Any]:
    global _session
    if not HAS_REQUESTS:
        return None

    # Double-checked locking for thread-safe singleton initialization
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                retry_strategy = Retry(
                    total=2,
                    backoff_factor=0.5,
                    status_forcelist=[429, 500, 502, 503, 504],
                )
                adapter = HTTPAdapter(max_retries=retry_strategy)
                session.mount("https://", adapter)
                session.mount("http://", adapter)

                # Security enhancement: Limit redirects and ignore environment proxies
                session.max_redirects = 3
                session.trust_env = False

                session.headers.update(
                    {
                        "User-Agent": "ClinicalTrialWatch/AutoDiscover/1.0",
                        "Accept": "application/json",
                    }
                )
                _session = session
    return _session


def search_trials(query_term: str) -> List[Dict[str, Any]]:
    """Search ClinicalTrials.gov API for a given term."""
    # Searching with max 1000 items (maximum allowed by pageSize)
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    params = {"query.term": query_term, "pageSize": "1000"}

    # Max response size: 10MB (to prevent memory exhaustion DoS)
    MAX_RESPONSE_SIZE = 10 * 1024 * 1024

    if HAS_REQUESTS:
        session = get_session()
        try:
            time.sleep(random.uniform(0.5, 1.0))  # Be polite to API
            # Use stream=True to check Content-Length before downloading full body
            with session.get(base_url, params=params, timeout=(5, 20), stream=True) as response:
                # Security enhancement: Verify final URL after redirects
                parsed_url = urlparse(response.url)
                if parsed_url.scheme != "https" or not (
                    parsed_url.netloc == "clinicaltrials.gov" or
                    parsed_url.netloc.endswith(".clinicaltrials.gov")
                ):
                    print(f"Error: Insecure or unexpected redirect for {query_term}: {response.url}")
                    return []

                if response.status_code == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith("application/json"):
                        print(f"Error: Unexpected Content-Type for {query_term}: {content_type}")
                        return []

                    # Check Content-Length header if present
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.strip().isdigit() and int(content_length) > MAX_RESPONSE_SIZE:
                        print(f"Error: Search response too large for {query_term}: {content_length} bytes")
                        return []

                    # Read in chunks to enforce limit
                    content = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(f"Error: Search response exceeded size limit for {query_term}")
                            return []
                        content.append(chunk)

                    data = json.loads(b"".join(content))
                    if not isinstance(data, dict):
                        print(f"Error: Malformed search response for {query_term} (not a dictionary)")
                        return []
                    return data.get("studies", [])
                else:
                    print(
                        f"Error fetching data for term {query_term}: {response.status_code}"
                    )
                    return []
        except Exception as e:
            print(f"Exception fetching data for term {query_term}: {e}")
            global _session
            with _session_lock:
                _session = None
            return []
    else:
        try:
            query_string = urllib.parse.urlencode(params)
            full_url = f"{base_url}?{query_string}"
            req = urllib.request.Request(full_url)
            req.add_header("User-Agent", "ClinicalTrialWatch/AutoDiscover/1.0")
            # Security enhancement: Add Accept header
            req.add_header("Accept", "application/json")
            time.sleep(random.uniform(0.5, 1.0))
            with urllib.request.urlopen(req, timeout=20) as response:
                # Security enhancement: Verify final URL after redirects for urllib
                final_url = response.geturl()
                parsed_url = urlparse(final_url)
                if parsed_url.scheme != "https" or not (
                    parsed_url.netloc == "clinicaltrials.gov" or
                    parsed_url.netloc.endswith(".clinicaltrials.gov")
                ):
                    print(f"Error: Insecure or unexpected redirect for {query_term} (urllib): {final_url}")
                    return []

                if response.status == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith("application/json"):
                        print(f"Error: Unexpected Content-Type for {query_term} (urllib): {content_type}")
                        return []

                    # Check Content-Length for urllib
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.strip().isdigit() and int(content_length) > MAX_RESPONSE_SIZE:
                        print(f"Error: Search response too large for {query_term}")
                        return []

                    content = []
                    size = 0
                    while True:
                        chunk = response.read(128 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(f"Error: Search response exceeded size limit for {query_term}")
                            return []
                        content.append(chunk)

                    data = json.loads(b"".join(content))
                    if not isinstance(data, dict):
                        print(f"Error: Malformed search response for {query_term} (urllib, not a dictionary)")
                        return []
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
                # Security enhancement: Truncate title to prevent DoS
                title = title[:1000]
                # Security enhancement: Validate NCT ID format
                if is_valid_nct_id(nct_id):
                    trials.append({"id": nct_id, "name": title})
                else:
                    print(f"  Warning: Skipping invalid NCT ID from API: {nct_id}")
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

        # Determine existing trials and excluded trials
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
