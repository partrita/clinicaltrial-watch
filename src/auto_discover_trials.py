"""
Auto-discover new clinical trials from ClinicalTrials.gov based on targets in trials.yaml.
Queries the API for each target and appends new trials to trials.yaml.
"""

import argparse
import contextlib
import random
import sys
import threading
import time
from typing import Any, Sequence
from urllib.parse import urlparse

try:
    from nct_search import query_variants, study_to_trial, trial_similarity
    from update_trials_from_csv import load_yaml, save_yaml, update_target
    from utils import (
        HAS_REQUESTS,
        MAX_CONFIG_SIZE,
        create_safe_session,
        is_valid_nct_id,
    )
except ImportError:
    from src.nct_search import query_variants, study_to_trial, trial_similarity
    from src.update_trials_from_csv import load_yaml, save_yaml, update_target
    from src.utils import (
        HAS_REQUESTS,
        MAX_CONFIG_SIZE,
        create_safe_session,
        is_valid_nct_id,
    )

import json
import ssl
import urllib.parse
import urllib.request

_session = None
_session_lock = threading.Lock()


def reset_session() -> None:
    """Reset the cached session (e.g. to apply new settings)."""
    global _session
    with _session_lock:
        if _session is not None and HAS_REQUESTS:
            with contextlib.suppress(Exception):
                _session.close()
        _session = None


def get_session() -> Any | None:
    global _session
    if not HAS_REQUESTS:
        return None

    # Double-checked locking for thread-safe singleton initialization
    if _session is None:
        with _session_lock:
            if _session is None:
                # Use centralized security-hardened session factory
                _session = create_safe_session(
                    user_agent="ClinicalTrialWatch/AutoDiscover/1.0 (https://github.com/partrita/clinicaltrial-watch)",
                    max_retries=2,
                )
    return _session


def search_trials(
    query_term: str, page_size: int = 1000, fields: str | None = None
) -> list[dict[str, Any]]:
    """Search ClinicalTrials.gov API for a given term."""
    # Searching with max 1000 items (maximum allowed by pageSize)
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    # pageSize is clamped to the range the API accepts
    page_size = max(1, min(int(page_size), 1000))
    params = {"query.term": query_term, "pageSize": str(page_size)}
    if fields:
        params["fields"] = fields

    # Max response size (to prevent memory exhaustion DoS)
    MAX_RESPONSE_SIZE = MAX_CONFIG_SIZE

    if HAS_REQUESTS:
        session = get_session()
        try:
            time.sleep(random.uniform(0.5, 1.0))  # Be polite to API
            # Use stream=True to check Content-Length before downloading full body
            with session.get(
                base_url, params=params, timeout=(5, 20), stream=True
            ) as response:
                # Security enhancement: Verify final URL after redirects
                parsed_url = urlparse(response.url)
                hostname = parsed_url.hostname or ""
                if parsed_url.scheme != "https" or not (
                    hostname == "clinicaltrials.gov"
                    or hostname.endswith(".clinicaltrials.gov")
                ):
                    print(
                        f"Error: Insecure or unexpected redirect for {query_term}: {response.url}"
                    )
                    return []

                if response.status_code == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith(
                        "application/json"
                    ):
                        print(
                            f"Error: Unexpected Content-Type for {query_term}: {content_type}"
                        )
                        return []

                    # Check Content-Length header if present
                    content_length = response.headers.get("Content-Length")
                    if (
                        content_length
                        and content_length.strip().isdigit()
                        and int(content_length) > MAX_RESPONSE_SIZE
                    ):
                        print(
                            f"Error: Search response too large for {query_term}: {content_length} bytes"
                        )
                        return []

                    # Read in chunks to enforce limit
                    content = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(
                                f"Error: Search response exceeded size limit for {query_term}"
                            )
                            return []
                        content.append(chunk)

                    try:
                        data = json.loads(b"".join(content))
                    except RecursionError:
                        print(
                            f"Error: Search response for {query_term} is too deeply nested (RecursionError)"
                        )
                        return []

                    if not isinstance(data, dict):
                        print(
                            f"Error: Malformed search response for {query_term} (not a dictionary)"
                        )
                        return []
                    studies = data.get("studies")
                    if not isinstance(studies, list):
                        print(
                            f"Error: 'studies' in search response for {query_term} is not a list"
                        )
                        return []
                    return studies
                else:
                    print(
                        f"Error fetching data for term {query_term}: {response.status_code}"
                    )
                    return []
        except (ValueError, KeyError, OSError, TypeError) as e:
            print(f"Exception fetching data for term {query_term}: {e}")
            reset_session()
            return []
    else:
        try:
            # Security enhancement: Disable environment proxies and ensure certificate verification
            context = ssl.create_default_context()
            # Security enhancement: Enforce TLS 1.2 or higher
            context.minimum_version = ssl.TLSVersion.TLSv1_2

            # Security enhancement: Limit redirects to 3
            redirect_handler = urllib.request.HTTPRedirectHandler()
            redirect_handler.max_redirections = 3

            # Security enhancement: Use restricted OpenerDirector to disable dangerous protocols (file://, ftp://, etc.)
            opener = urllib.request.OpenerDirector()
            for handler in [
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=context),
                redirect_handler,
                urllib.request.HTTPDefaultErrorHandler(),
                urllib.request.HTTPErrorProcessor(),
                urllib.request.UnknownHandler(),
            ]:
                opener.add_handler(handler)
            query_string = urllib.parse.urlencode(params)
            full_url = f"{base_url}?{query_string}"
            req = urllib.request.Request(full_url)
            req.add_header(
                "User-Agent",
                "ClinicalTrialWatch/AutoDiscover/1.0 (https://github.com/partrita/clinicaltrial-watch)",
            )
            # Security enhancement: Add Accept header
            req.add_header("Accept", "application/json")
            time.sleep(random.uniform(0.5, 1.0))
            with opener.open(req, timeout=20) as response:
                # Security enhancement: Verify final URL after redirects for urllib
                final_url = response.geturl()
                parsed_url = urlparse(final_url)
                hostname = parsed_url.hostname or ""
                if parsed_url.scheme != "https" or not (
                    hostname == "clinicaltrials.gov"
                    or hostname.endswith(".clinicaltrials.gov")
                ):
                    print(
                        f"Error: Insecure or unexpected redirect for {query_term} (urllib): {final_url}"
                    )
                    return []

                if response.status == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith(
                        "application/json"
                    ):
                        print(
                            f"Error: Unexpected Content-Type for {query_term} (urllib): {content_type}"
                        )
                        return []

                    # Check Content-Length for urllib
                    content_length = response.headers.get("Content-Length")
                    if (
                        content_length
                        and content_length.strip().isdigit()
                        and int(content_length) > MAX_RESPONSE_SIZE
                    ):
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
                            print(
                                f"Error: Search response exceeded size limit for {query_term}"
                            )
                            return []
                        content.append(chunk)

                    try:
                        data = json.loads(b"".join(content))
                    except RecursionError:
                        print(
                            f"Error: Search response for {query_term} is too deeply nested (urllib, RecursionError)"
                        )
                        return []

                    if not isinstance(data, dict):
                        print(
                            f"Error: Malformed search response for {query_term} (urllib, not a dictionary)"
                        )
                        return []
                    studies = data.get("studies")
                    if not isinstance(studies, list):
                        print(
                            f"Error: 'studies' in search response for {query_term} (urllib) is not a list"
                        )
                        return []
                    return studies
                else:
                    print(
                        f"Error fetching data for term {query_term} (urllib): {response.status}"
                    )
                    return []
        except (
            urllib.error.URLError,
            ssl.SSLError,
            ValueError,
            KeyError,
            OSError,
        ) as e:
            print(f"Exception fetching data for term {query_term} (urllib): {e}")
            return []


def extract_trials(api_studies: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract required trial info from API response."""
    if not isinstance(api_studies, list):
        print("Error: api_studies must be a list")
        return []

    # Security enhancement: Limit number of studies to process to prevent DoS (CWE-400)
    MAX_API_STUDIES = 2000
    if len(api_studies) > MAX_API_STUDIES:
        print(f"Warning: api_studies exceeds limit of {MAX_API_STUDIES}. Truncating.")
        api_studies = api_studies[:MAX_API_STUDIES]

    trials = []
    for study in api_studies:
        try:
            protocol = study.get("protocolSection")
            if not isinstance(protocol, dict):
                protocol = {}
            identity = protocol.get("identificationModule")
            if not isinstance(identity, dict):
                identity = {}
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
        except (AttributeError, TypeError, KeyError) as e:
            print(f"Error extracting study data: {e}")
    return trials


# Minimum similarity for a trial that only the widened (fuzzy) queries found.
# Trials returned by the plain keyword search are always kept, as before.
FUZZY_MIN_SCORE = 0.7


def search_trials_fuzzy(
    target_name: str, known_names: Sequence[str] = ()
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Search for a target the way a person writes it, not only literally.

    The plain keyword search runs first. It is then widened with normalized
    variants of the name (hyphen/space removed or swapped, and the closest
    tracked target name) so that 'B7H3' also finds studies titled 'B7-H3'.
    Studies that only the widened queries found are kept when they actually
    mention the target in their title or interventions.

    Returns the combined study list and the variants that were searched.
    """
    primary = search_trials(target_name)
    variants = query_variants(target_name, known_names)

    seen = set()
    for study in primary:
        trial = study_to_trial(study)
        if trial:
            seen.add(trial["id"])

    combined = list(primary)
    for variant in variants[1:]:
        for study in search_trials(variant):
            trial = study_to_trial(study)
            if not trial or trial["id"] in seen:
                continue
            seen.add(trial["id"])
            score, _ = trial_similarity(target_name, trial)
            if score >= FUZZY_MIN_SCORE:
                combined.append(study)

    return combined, variants


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover new clinical trials for the targets in trials.yaml."
    )
    parser.add_argument(
        "--yaml",
        "-y",
        default="trials.yaml",
        help="Path to trials.yaml (default: trials.yaml)",
    )
    parser.add_argument(
        "--no-fuzzy",
        action="store_true",
        help="Search only the exact target name, without widening the query",
    )
    args = parser.parse_args(argv)
    yaml_path = args.yaml

    print("Loading existing trials...")
    data = load_yaml(yaml_path)

    targets = data.get("targets", [])
    if not targets:
        print("No targets found in trials.yaml. Nothing to auto-discover.")
        return 0

    total_added = 0

    # Names already tracked, so a target written differently still searches well.
    known_names = [
        target["name"]
        for target in targets
        if isinstance(target, dict) and target.get("name")
    ]

    for target in targets:
        target_name = target["name"]
        print(f"\nSearching for '{target_name}' on ClinicalTrials.gov...")

        if args.no_fuzzy:
            api_studies, variants = search_trials(target_name), [target_name]
        else:
            api_studies, variants = search_trials_fuzzy(target_name, known_names)
        if len(variants) > 1:
            print(f"  Fuzzy query variants: {variants}")
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
    sys.exit(main())
