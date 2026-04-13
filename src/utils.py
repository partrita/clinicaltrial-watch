import re
import html
from typing import Any
from functools import lru_cache


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
    # Remove leading/trailing underscores and prevent empty string
    sanitized = sanitized.strip("_")
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
    Dangerous characters: '=', '+', '-', '@', ';', '%', tab (0x09), or carriage return (0x0D).
    Length limited to 32,767 characters to prevent DoS and comply with Excel cell limits.
    """
    if not isinstance(value, str) or not value:
        return value

    # Limit length to prevent DoS and comply with Excel's 32,767 character limit per cell
    value = value[:32767]

    # Check the first non-whitespace character
    stripped_value = value.lstrip()
    if not stripped_value:
        return value

    if stripped_value[0] in ("=", "+", "-", "@", ";", "%", "\t", "\r", "\n"):
        return f"'{value}"
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
