import contextlib
import json
import os
import random
import threading
import time
from typing import Any
from urllib.parse import urlparse

try:
    from utils import (
        HAS_REQUESTS,
        MAX_CONFIG_SIZE,
        atomic_write,
        create_safe_session,
        is_valid_nct_id,
        sanitize_id,
    )
except ImportError:
    from src.utils import (
        HAS_REQUESTS,
        MAX_CONFIG_SIZE,
        atomic_write,
        create_safe_session,
        is_valid_nct_id,
        sanitize_id,
    )

import ssl
import urllib.request

# Global session to reuse connections (much faster)
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
    """Returns a requests session with retry logic and custom headers."""
    global _session
    if not HAS_REQUESTS:
        return None

    # Double-checked locking for thread-safe singleton initialization
    if _session is None:
        with _session_lock:
            if _session is None:
                # Use centralized security-hardened session factory
                # Increase pool size to match MAX_WORKERS in main.py for better concurrency
                _session = create_safe_session(
                    user_agent="ClinicalTrialWatch/1.0 (https://github.com/partrita/clinicaltrial-watch)",
                    max_retries=2,
                    pool_size=20,
                )
    return _session


def fetch_trial_data(trial_id: str) -> dict[str, Any] | None:
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

    # Max response size (to prevent memory exhaustion DoS)
    MAX_RESPONSE_SIZE = MAX_CONFIG_SIZE

    if HAS_REQUESTS:
        session = get_session()
        try:
            # Adding a tiny random jitter to avoid perfectly synchronized requests
            time.sleep(random.uniform(0.05, 0.1))

            # Use stream=True to check Content-Length before downloading full body
            with session.get(url, timeout=(3, 15), stream=True) as response:
                # Security enhancement: Verify final URL after redirects
                parsed_url = urlparse(response.url)
                hostname = parsed_url.hostname or ""
                if parsed_url.scheme != "https" or not (
                    hostname == "clinicaltrials.gov"
                    or hostname.endswith(".clinicaltrials.gov")
                ):
                    print(
                        f"Error: Insecure or unexpected redirect for {safe_trial_id}: {response.url}"
                    )
                    return None

                if response.status_code == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith(
                        "application/json"
                    ):
                        print(
                            f"Error: Unexpected Content-Type for {safe_trial_id}: {content_type}"
                        )
                        return None

                    # Check Content-Length header if present
                    content_length = response.headers.get("Content-Length")
                    if (
                        content_length
                        and content_length.strip().isdigit()
                        and int(content_length) > MAX_RESPONSE_SIZE
                    ):
                        print(
                            f"Error: Response too large for {safe_trial_id}: {content_length} bytes"
                        )
                        return None

                    # Read in chunks to enforce limit even if header is missing/wrong
                    content = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(
                                f"Error: Response exceeded size limit for {safe_trial_id}"
                            )
                            return None
                        content.append(chunk)

                    try:
                        data = json.loads(b"".join(content))
                    except RecursionError:
                        print(
                            f"Error: JSON response for {safe_trial_id} is too deeply nested (RecursionError)"
                        )
                        return None

                    if not isinstance(data, dict):
                        print(
                            f"Error: Malformed JSON response for {safe_trial_id} (not a dictionary)"
                        )
                        return None
                    return data
                elif response.status_code == 404:
                    print(f"Trial {safe_trial_id} not found (404).")
                    return None
                else:
                    print(
                        f"Error fetching data for {safe_trial_id}: {response.status_code}"
                    )
                    return None
        except (ValueError, KeyError, OSError, TypeError) as e:
            print(f"Exception fetching data for {safe_trial_id}: {e}")
            # Reset session on connection errors to avoid stuck connections
            reset_session()
            return None
    else:
        # Fallback to urllib if requests is not available
        try:
            # Adding a tiny random jitter to avoid perfectly synchronized requests
            time.sleep(random.uniform(0.05, 0.1))

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
            req = urllib.request.Request(url)
            req.add_header(
                "User-Agent",
                "ClinicalTrialWatch/1.0 (https://github.com/partrita/clinicaltrial-watch)",
            )
            # Security enhancement: Add Accept header
            req.add_header("Accept", "application/json")
            with opener.open(req, timeout=15) as response:
                # Security enhancement: Verify final URL after redirects for urllib
                final_url = response.geturl()
                parsed_url = urlparse(final_url)
                hostname = parsed_url.hostname or ""
                if parsed_url.scheme != "https" or not (
                    hostname == "clinicaltrials.gov"
                    or hostname.endswith(".clinicaltrials.gov")
                ):
                    print(
                        f"Error: Insecure or unexpected redirect for {safe_trial_id} (urllib): {final_url}"
                    )
                    return None

                if response.status == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith(
                        "application/json"
                    ):
                        print(
                            f"Error: Unexpected Content-Type for {safe_trial_id} (urllib): {content_type}"
                        )
                        return None

                    # Check Content-Length for urllib
                    content_length = response.headers.get("Content-Length")
                    if (
                        content_length
                        and content_length.strip().isdigit()
                        and int(content_length) > MAX_RESPONSE_SIZE
                    ):
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
                            print(
                                f"Error: Response exceeded size limit for {safe_trial_id}"
                            )
                            return None
                        content.append(chunk)

                    try:
                        data = json.loads(b"".join(content))
                    except RecursionError:
                        print(
                            f"Error: JSON response for {safe_trial_id} is too deeply nested (urllib, RecursionError)"
                        )
                        return None

                    if not isinstance(data, dict):
                        print(
                            f"Error: Malformed JSON response for {safe_trial_id} (urllib, not a dictionary)"
                        )
                        return None
                    return data
                else:
                    print(
                        f"Error fetching data for {safe_trial_id} (urllib): {response.status}"
                    )
                    return None
        except (
            urllib.error.URLError,
            ssl.SSLError,
            ValueError,
            KeyError,
            OSError,
            TypeError,
        ) as e:
            print(f"Exception fetching data for {safe_trial_id} (urllib): {e}")
            return None


def save_snapshot(
    trial_id: str, data: dict[str, Any], snapshot_dir: str = "data/snapshots"
) -> str:
    """
    Saves the fetched data as a JSON snapshot.
    """
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir, exist_ok=True)

    # Sanitize trial_id to prevent path traversal
    safe_trial_id = sanitize_id(trial_id)
    filepath = os.path.join(snapshot_dir, f"{safe_trial_id}_latest.json")

    # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
    with atomic_write(filepath, encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(data, f, ensure_ascii=False)
    return filepath
