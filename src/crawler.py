import json
import os
import time
import random
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from utils import sanitize_id, is_valid_nct_id, atomic_write

import ssl
import urllib.request

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    HAS_REQUESTS = True

    class TLSAdapter(HTTPAdapter):
        """
        Custom HTTPAdapter that enforces TLS 1.2 or higher for requests.
        """

        def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            pool_kwargs["ssl_context"] = ctx
            return super(TLSAdapter, self).init_poolmanager(
                connections, maxsize, block, **pool_kwargs
            )

        def proxy_manager_for(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            kwargs["ssl_context"] = ctx
            return super(TLSAdapter, self).proxy_manager_for(*args, **kwargs)

except ImportError:
    HAS_REQUESTS = False

# Global session to reuse connections (much faster)
_session = None
_session_lock = threading.Lock()


def reset_session() -> None:
    """Reset the cached session (e.g. to apply new settings)."""
    global _session
    with _session_lock:
        if _session is not None and HAS_REQUESTS:
            try:
                _session.close()
            except Exception:
                pass
        _session = None


def get_session() -> Optional[Any]:
    """Returns a requests session with retry logic and custom headers."""
    global _session
    if not HAS_REQUESTS:
        return None

    # Double-checked locking for thread-safe singleton initialization
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                # ClinicalTrials.gov API v2 is generally fast, but retries help with transient issues
                retry_strategy = Retry(
                    total=2,
                    backoff_factor=0.5,
                    status_forcelist=[429, 500, 502, 503, 504],
                )
                # Increase pool size to match MAX_WORKERS in main.py for better concurrency
                # Security enhancement: Use TLSAdapter to enforce TLS 1.2+ for HTTPS
                https_adapter = TLSAdapter(
                    max_retries=retry_strategy, pool_connections=20, pool_maxsize=20
                )
                http_adapter = HTTPAdapter(
                    max_retries=retry_strategy, pool_connections=20, pool_maxsize=20
                )
                session.mount("https://", https_adapter)
                session.mount("http://", http_adapter)

                # Security enhancement: Limit redirects and ignore environment proxies
                session.max_redirects = 3
                session.trust_env = False

                # User-Agent is good practice to avoid being flagged as a generic bot
                session.headers.update(
                    {
                        "User-Agent": "ClinicalTrialWatch/1.0 (https://github.com/partrita/clinicaltrial-watch)",
                        "Accept": "application/json",
                    }
                )
                _session = session
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
            with session.get(url, timeout=(3, 15), stream=True) as response:
                # Security enhancement: Verify final URL after redirects
                parsed_url = urlparse(response.url)
                hostname = parsed_url.hostname or ""
                if parsed_url.scheme != "https" or not (
                    hostname == "clinicaltrials.gov" or
                    hostname.endswith(".clinicaltrials.gov")
                ):
                    print(f"Error: Insecure or unexpected redirect for {safe_trial_id}: {response.url}")
                    return None

                if response.status_code == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith("application/json"):
                        print(f"Error: Unexpected Content-Type for {safe_trial_id}: {content_type}")
                        return None

                    # Check Content-Length header if present
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.strip().isdigit() and int(content_length) > MAX_RESPONSE_SIZE:
                        print(f"Error: Response too large for {safe_trial_id}: {content_length} bytes")
                        return None

                    # Read in chunks to enforce limit even if header is missing/wrong
                    content = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_SIZE:
                            print(f"Error: Response exceeded size limit for {safe_trial_id}")
                            return None
                        content.append(chunk)

                    data = json.loads(b"".join(content))
                    if not isinstance(data, dict):
                        print(f"Error: Malformed JSON response for {safe_trial_id} (not a dictionary)")
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
        except Exception as e:
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
                    hostname == "clinicaltrials.gov" or
                    hostname.endswith(".clinicaltrials.gov")
                ):
                    print(f"Error: Insecure or unexpected redirect for {safe_trial_id} (urllib): {final_url}")
                    return None

                if response.status == 200:
                    # Security enhancement: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type or not content_type.lower().startswith("application/json"):
                        print(f"Error: Unexpected Content-Type for {safe_trial_id} (urllib): {content_type}")
                        return None

                    # Check Content-Length for urllib
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.strip().isdigit() and int(content_length) > MAX_RESPONSE_SIZE:
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

                    data = json.loads(b"".join(content))
                    if not isinstance(data, dict):
                        print(f"Error: Malformed JSON response for {safe_trial_id} (urllib, not a dictionary)")
                        return None
                    return data
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

    # Security enhancement: Use atomic write to prevent data corruption (CWE-459)
    with atomic_write(filepath, encoding="utf-8") as f:
        # Optimized: Removed indent to reduce serialization time and file size
        json.dump(data, f, ensure_ascii=False)
    return filepath
