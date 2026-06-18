import re
import os
import html
import tempfile
import contextlib
import ssl
from typing import Any, Optional
from functools import lru_cache

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

    class BlockedAdapter(HTTPAdapter):
        """
        Adapter that explicitly blocks requests by raising an exception.
        Used to disable insecure protocols (CWE-319, CWE-918).
        """

        def send(self, request, *args, **kwargs):
            from requests.exceptions import InvalidSchema

            raise InvalidSchema(
                f"Insecure protocol blocked: {request.url}. "
                "Only HTTPS is allowed for security reasons."
            )

except ImportError:
    HAS_REQUESTS = False


# Configuration limits for DoS protection (CWE-400)
MAX_CONFIG_SIZE = 10 * 1024 * 1024  # 10MB limit for local YAML/JSON config and data files


def check_file_size(filepath: str, max_size: int = MAX_CONFIG_SIZE) -> None:
    """
    Check if a file exists and its size is within the limit.
    Also ensures it is a regular file (not a directory or special device).
    Raises ValueError if the file is too large or is not a regular file.
    """
    if os.path.exists(filepath):
        if not os.path.isfile(filepath):
            raise ValueError(f"Not a regular file: {filepath}")
        try:
            size = os.path.getsize(filepath)
            if size > max_size:
                raise ValueError(
                    f"File too large: {filepath} ({size} bytes, limit: {max_size} bytes)"
                )
        except OSError as e:
            # Re-raise as OSError to be handled by the caller's specific error handling
            raise OSError(f"Error checking file size for {filepath}: {e}") from e


# List of dangerous characters that can trigger formula execution in Excel/Google Sheets
# Also includes '|' (pipe) as a defensive measure against downstream parser confusion.
DANGEROUS_CSV_CHARS = {"=", "+", "-", "@", ";", "%", "|", "\t", "\r", "\n", "\v", "\f", "\x1b", "`"}


# Pre-compiled regex for NCT ID validation (faster than string pattern)
# Uses \A and \Z for strict start/end of string matching.
# Uses [0-9] instead of \d to ensure only ASCII digits are matched.
NCT_ID_PATTERN = re.compile(r"\ANCT[0-9]{8}\Z")


def is_valid_nct_id(nct_id: str) -> bool:
    """
    Check if a string is a valid ClinicalTrials.gov NCT ID.
    Format: NCT followed by 8 digits.
    Length limited to 32 characters for defense-in-depth.
    """
    if not nct_id or not isinstance(nct_id, str) or len(nct_id) > 32:
        return False
    return bool(NCT_ID_PATTERN.match(nct_id))


@lru_cache(maxsize=1024)
def _sanitize_id_cached(identifier: str) -> str:
    """Internal cached helper for sanitize_id."""
    # Replace any non-alphanumeric, non-dash, non-underscore characters with an underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", identifier)
    # Security enhancement: Remove leading/trailing underscores AND dashes
    # This prevents identifiers from being interpreted as command-line flags (CWE-88)
    # when used as filenames in downstream tools or scripts.
    sanitized = sanitized.strip("_-")
    return sanitized if sanitized else "unknown"


def sanitize_id(identifier: str) -> str:
    """
    Sanitize an identifier (trial ID or target name) to prevent
    path traversal and code injection.
    Allows only alphanumeric characters, dashes, and underscores.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not identifier:
        return "unknown"

    # Limit identifier length before caching
    safe_identifier = str(identifier)[:255]
    return _sanitize_id_cached(safe_identifier)


# Pre-computed translation table for Markdown/Quarto specific escapes
# Performance: ~15-20% faster than multiple .replace() calls
# Also escapes '$' to prevent MathJax injection, '\' for general Markdown safety,
# and curly braces '{}' to prevent Quarto/Pandoc attribute injection.
# Security enhancement: Added ':' to prevent breaking out of
# Quarto/Pandoc attribute blocks.
# Note: '#' is intentionally omitted because it conflicts with HTML entities
# produced by html.escape (e.g., ' escaped as &#x27;).
MARKDOWN_ESCAPE_TABLE = str.maketrans(
    {
        "|": "&#124;",
        "[": "&#91;",
        "]": "&#93;",
        "`": "&#96;",
        "$": "&#36;",
        "\\": "&#92;",
        "{": "&#123;",
        "}": "&#125;",
        ":": "&#58;",
        "=": "&#61;",
    }
)


@lru_cache(maxsize=1024)
def _escape_html_cached(text: str) -> str:
    """Internal cached helper for escape_html."""
    # html.escape is fast, then use .translate() for bulk character replacement
    return html.escape(text).translate(MARKDOWN_ESCAPE_TABLE)


def escape_html(text: str) -> str:
    """
    Escape HTML special characters in a string.
    Also explicitly escapes the pipe character '|', brackets '[' ']',
    backticks '`', and MathJax '$' to prevent injection in generated pages.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if text is None:
        return ""

    # Limit length before caching to prevent memory exhaustion from large keys
    text_str = str(text)[:65536]
    return _escape_html_cached(text_str)


def sanitize_csv_value(value: Any) -> Any:
    """
    Sanitize a value for CSV export to prevent formula injection.
    If the value is a string that starts with dangerous characters
    (even after leading whitespace), it is prefixed with a single quote.
    Dangerous characters: '=', '+', '-', '@', ';', '%', tab (0x09), carriage return (0x0D),
    line feed (0x0A), vertical tab (0x0B), form feed (0x0C), or ESC (0x1B).
    Length limited to 32,767 characters to prevent DoS and comply with Excel cell limits.
    """
    if not isinstance(value, str) or not value:
        return value

    # Limit length to prevent DoS and comply with Excel's 32,767 character limit per cell
    value = value[:32767]

    # Check the original first character (safe because value is non-empty string here)
    if value[0] in DANGEROUS_CSV_CHARS:
        # Truncate to 32,766 so that prepending a quote doesn't exceed 32,767
        return f"'{value[:32766]}"

    # Check the first non-whitespace and non-invisible character to prevent bypasses.
    # We use a regex to strip leading whitespace and invisible characters (like
    # Zero Width Space or BOM) that could be used to hide a formula.
    # This prevents bypasses like "\u200B=SUM(1+1)" or " \u200B =SUM(1+1)".
    # Added \u00A0 (NBSP), \u00AD (SHY), \u034F (CGJ), \u1680 (Ogham space mark),
    # \u2028, \u2029 (separators), \u202F (Nnbs), \u205F (Mmsp), \u3000 (Ideographic space),
    # and \u180E (MVS) for completeness.
    # Also includes Variation Selectors (U+FE00-U+FE0F), Unicode fillers
    # (U+115F, U+1160, U+3164, U+FFA0, U+2800), Mongolian Free Variation Selectors
    # (U+180B-U+180D), Unicode Tag Characters (U+E0020-U+E007F), and
    # C1 control characters (U+0080-U+009F) for enhanced defense.
    stripped_value = re.sub(
        r"^[\s\x00-\x1f\u0080-\u009f\u00a0\u00ad\u034f\u1680\u200b-\u200f\u2028-\u202f\u205f\u2060-\u206f\u3000\uFEFF\u180b-\u180e\ufe00-\ufe0f\u115f\u1160\u3164\uffa0\u2800\U000E0020-\U000E007F]+", "", value
    )
    if stripped_value and stripped_value[0] in DANGEROUS_CSV_CHARS:
        return f"'{value[:32766]}"

    return value


# Pre-compiled regex for diff formatting
# Updated to match escaped backticks (&#96;) for security and robust highlighting.
# The second value uses greedy matching to ensure it captures the full new value
# even if it contains inner escaped backticks.
DIFF_CHANGE_PATTERN = re.compile(r"(changed from )(&#96;.*?&#96;)( to )(&#96;.*&#96;)")


def _replace_diff_match(match: re.Match) -> str:
    """Helper for format_diff_line to avoid nested function overhead."""
    prefix = match.group(1)
    old_val = match.group(2)
    connector = match.group(3)
    new_val = match.group(4)

    return (
        f"{prefix}<span class='text-danger fw-bold'>{old_val}</span>"
        f"{connector}<span class='text-success fw-bold'>{new_val}</span>"
    )


def _replace_diff_match_markdown(match: re.Match) -> str:
    """Helper for format_diff_line_markdown to avoid nested function overhead."""
    prefix = match.group(1)
    old_val = match.group(2)
    connector = match.group(3)
    new_val = match.group(4)

    # Use Markdown bolding instead of HTML span tags
    return f"{prefix}**{old_val}**{connector}**{new_val}**"


# Global map for status to bootstrap_class
STATUS_CONFIGS = {
    "RECRUITING": "success",
    "ACTIVE_NOT_RECRUITING": "info",
    "COMPLETED": "secondary",
    "NOT_YET_RECRUITING": "warning",
    "SUSPENDED": "danger",
    "TERMINATED": "danger",
    "WITHDRAWN": "danger",
}

# Global map for phase to bootstrap_class
PHASE_CONFIGS = {
    "PHASE1": "primary",
    "PHASE2": "info",
    "PHASE3": "warning",
    "PHASE4": "success",
    "EARLY_PHASE1": "primary",
}


@lru_cache(maxsize=1024)
def _get_status_badge_cached(status: str) -> str:
    """Internal cached helper for get_status_badge."""
    bg_class = STATUS_CONFIGS.get(status, "light text-dark")
    safe_status = escape_html(status.replace("_", " ").title())
    return f'<span class="badge bg-{bg_class}">{safe_status}</span>'


def get_status_badge(status: str) -> str:
    """
    Return a Bootstrap badge for a trial status.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not status:
        return ""
    # Limit status string length before caching
    safe_status = str(status)[:255]
    return _get_status_badge_cached(safe_status)


@lru_cache(maxsize=1024)
def _get_phase_badge_cached(phase: str) -> str:
    """Internal cached helper for get_phase_badge."""
    if not phase or phase == "N/A":
        return escape_html("N/A")

    phases = [p.strip() for p in phase.split(",")]
    badges = []
    for p in phases:
        key = p.upper().replace(" ", "")
        bg_class = PHASE_CONFIGS.get(key, "light text-dark")
        safe_phase = escape_html(p)
        badges.append(f'<span class="badge bg-{bg_class}">{safe_phase}</span>')

    return " ".join(badges)


def get_phase_badge(phase: str) -> str:
    """
    Return Bootstrap badges for trial phases.
    Handles multi-phase strings (e.g., 'PHASE1, PHASE2') by splitting.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not phase:
        return escape_html("N/A")

    # Limit phase string length before caching
    safe_phase = str(phase)[:255]
    return _get_phase_badge_cached(safe_phase)


@lru_cache(maxsize=1024)
def _get_update_badge_cached(monitor_status: str, last_change_date: str = None) -> str:
    """Internal cached helper for get_update_badge."""
    safe_status = escape_html(monitor_status)
    title_attr = ""
    if last_change_date:
        safe_date = escape_html(last_change_date)
        title_attr = f' title="Last changed: {safe_date}"'

    if monitor_status == "Changed":
        return f'<span class="badge bg-danger"{title_attr}>{safe_status}</span>'
    return f'<span class="badge bg-success"{title_attr}>{safe_status}</span>'


def get_update_badge(monitor_status: str, last_change_date: str = None) -> str:
    """
    Return a badge for monitoring status.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not monitor_status:
        return ""

    # Limit string lengths before caching
    safe_status = str(monitor_status)[:255]
    safe_date = str(last_change_date)[:255] if last_change_date else None
    return _get_update_badge_cached(safe_status, safe_date)


@lru_cache(maxsize=1024)
def _format_truncated_with_tooltip_cached(text: str, max_length: int) -> str:
    """Internal cached helper for format_truncated_with_tooltip."""
    if len(text) <= max_length:
        return escape_html(text)

    truncated = text[:max_length] + "..."
    safe_full = escape_html(text)
    safe_truncated = escape_html(truncated)

    return f'<span class="truncated-text" tabindex="0" role="note" aria-label="{safe_full}" title="{safe_full}">{safe_truncated}</span>'


def format_truncated_with_tooltip(text: str, max_length: int = 30) -> str:
    """
    Truncate text and provide a tooltip with the full text.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not text:
        return ""

    # Limit total text length before caching
    safe_text = str(text)[:10000]
    return _format_truncated_with_tooltip_cached(safe_text, max_length)


@lru_cache(maxsize=1024)
def get_changed_count_badge(count: int) -> str:
    """Return a badge for changed trial count."""
    safe_count = escape_html(str(count))
    if count > 0:
        return f'<span class="badge bg-danger" aria-label="{safe_count} trials changed">{safe_count}</span>'
    return f'<span class="badge bg-success" aria-label="0 trials changed">0</span>'


@lru_cache(maxsize=1024)
def _format_enrollment_cached(value_str: str) -> str:
    """Internal cached helper for format_enrollment."""
    if value_str == "N/A" or not value_str:
        return "N/A"
    try:
        # Handle cases where value might be a float string or already has commas
        num_val = int(float(value_str.replace(",", "")))
        return f"{num_val:,}"
    except (ValueError, TypeError, OverflowError):
        return "N/A"


def format_enrollment(value: Any) -> str:
    """
    Format enrollment number with commas (e.g., 1,234) for better numerical readability.
    Returns 'N/A' for None, empty, or non-numeric inputs.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if value is None or value == "" or value == "N/A":
        return "N/A"

    # Limit string length before caching
    safe_value = str(value)[:255]
    return _format_enrollment_cached(safe_value)


@lru_cache(maxsize=1024)
def _format_diff_line_cached(line: str) -> str:
    """Internal cached helper for format_diff_line."""
    escaped_line = escape_html(line)

    # Highlight additions/removals with Bootstrap classes
    if escaped_line.startswith("New field added:"):
        return f"<span class='text-success fw-bold'>{escaped_line}</span>"
    if escaped_line.startswith("Field removed:"):
        return f"<span class='text-danger fw-bold'>{escaped_line}</span>"

    return DIFF_CHANGE_PATTERN.sub(_replace_diff_match, escaped_line)


def format_diff_line(line: str) -> str:
    """
    Format a diff line with color-coded changes.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not line:
        return ""

    # Limit line length before caching
    safe_line = str(line)[:10000]
    return _format_diff_line_cached(safe_line)


@lru_cache(maxsize=1024)
def _format_diff_line_markdown_cached(line: str) -> str:
    """Internal cached helper for format_diff_line_markdown."""
    escaped_line = escape_html(line)

    # Highlight additions/removals with Markdown bolding
    if escaped_line.startswith("New field added:"):
        return f"**{escaped_line}**"
    if escaped_line.startswith("Field removed:"):
        return f"**{escaped_line}**"

    return DIFF_CHANGE_PATTERN.sub(_replace_diff_match_markdown, escaped_line)


def format_diff_line_markdown(line: str) -> str:
    """
    Format a diff line with Markdown bolding for changes.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not line:
        return ""

    # Limit line length before caching
    safe_line = str(line)[:10000]
    return _format_diff_line_markdown_cached(safe_line)


def create_safe_session(
    user_agent: str, max_retries: int = 2, pool_size: int = 10
) -> Optional[Any]:
    """
    Creates and returns a security-hardened requests.Session object.
    Enforces TLS 1.2+, limited redirects, and safe environment defaults.
    """
    if not HAS_REQUESTS:
        return None

    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )

    # Mount TLSAdapter to enforce TLS 1.2+ for HTTPS
    https_adapter = TLSAdapter(
        max_retries=retry_strategy, pool_connections=pool_size, pool_maxsize=pool_size
    )
    # Security hardening: Explicitly block insecure HTTP requests (CWE-319, CWE-918)
    blocked_adapter = BlockedAdapter()

    session.mount("https://", https_adapter)
    session.mount("http://", blocked_adapter)

    # Security hardening: Limit redirects to prevent DoS via redirect loops (CWE-606)
    session.max_redirects = 3

    # Security hardening: Ignore proxy environment variables to prevent hijacking (CWE-918)
    session.trust_env = False

    # Set default headers
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "application/json",
        }
    )

    return session


@contextlib.contextmanager
def atomic_write(
    filepath: str, mode: str = "w", encoding: str = "utf-8", newline: Optional[str] = None
):
    """
    Context manager for atomic file writes.
    Writes to a temporary file and replaces the target file only on success (CWE-459).
    This prevents data corruption or partial writes if the process is interrupted.
    """
    parent_dir = os.path.dirname(os.path.abspath(filepath))
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    # Create temp file in the same directory to ensure os.replace works (same filesystem)
    # We use delete=False because we handle the replacement/cleanup ourselves.
    tmppath = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            dir=parent_dir,
            encoding=encoding,
            newline=newline,
            delete=False,
        ) as tf:
            tmppath = tf.name
            yield tf
            tf.flush()
            try:
                os.fsync(tf.fileno())
            except OSError:
                # Some systems/filesystems don't support fsync on all file types
                pass

        # After successfully closing the context, replace the original file
        os.replace(tmppath, filepath)
    except Exception:
        # If any error occurred, try to remove the temporary file
        if tmppath and os.path.exists(tmppath):
            try:
                os.remove(tmppath)
            except OSError:
                pass
        raise
