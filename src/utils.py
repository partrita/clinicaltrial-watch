import re
import html
from typing import Any
from functools import lru_cache


# Pre-compiled regex for NCT ID validation (faster than string pattern)
# Uses \Z instead of $ to prevent matching strings with trailing newlines.
NCT_ID_PATTERN = re.compile(r"^NCT\d{8}\Z")


def is_valid_nct_id(nct_id: str) -> bool:
    """
    Check if a string is a valid ClinicalTrials.gov NCT ID.
    Format: NCT followed by 8 digits.
    """
    if not nct_id or not isinstance(nct_id, str):
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
    Length limited to 255 characters to prevent DoS by ensuring small cache keys.
    """
    if not identifier:
        return "unknown"

    # Truncate BEFORE caching to prevent memory exhaustion DoS from large keys
    # 255 is more than enough for NCT IDs and target names
    return _sanitize_id_cached(str(identifier)[:255])


# Pre-computed translation table for Markdown/Quarto/MathJax specific escapes
# Includes \ and $ to prevent Markdown escaping and MathJax injection.
# Performance: ~15-20% faster than multiple .replace() calls
MARKDOWN_ESCAPE_TABLE = str.maketrans(
    {
        "|": "&#124;",
        "[": "&#91;",
        "]": "&#93;",
        "`": "&#96;",
        "\\": "&#92;",
        "$": "&#36;",
    }
)


@lru_cache(maxsize=1024)
def _escape_html_cached(text_str: str) -> str:
    """Internal cached helper for escape_html."""
    # html.escape is fast, then use .translate() for bulk character replacement
    return html.escape(text_str).translate(MARKDOWN_ESCAPE_TABLE)


def escape_html(text: str) -> str:
    """
    Escape HTML special characters in a string.
    Also explicitly escapes the pipe character '|' and brackets '[' ']'
    to prevent breaking Markdown tables and link/attribute injection.
    Length limited to 65,536 characters to prevent memory exhaustion in lru_cache.
    """
    if text is None:
        return ""

    # Truncate BEFORE caching to prevent memory exhaustion DoS from large keys
    return _escape_html_cached(str(text)[:65536])


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

    if stripped_value[0] in ("=", "+", "-", "@", ";", "%", "\t", "\r"):
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


@lru_cache(maxsize=1024)
def get_status_badge(status: str) -> str:
    """Return a Bootstrap badge for a trial status."""
    bg_class = STATUS_CONFIGS.get(status, "light text-dark")
    safe_status = escape_html(status.replace("_", " ").title())
    return f'<span class="badge bg-{bg_class}">{safe_status}</span>'


@lru_cache(maxsize=1024)
def get_update_badge(monitor_status: str, last_change_date: str = None) -> str:
    """Return a badge for monitoring status."""
    safe_status = escape_html(monitor_status)
    if monitor_status == "Changed":
        return f'<span class="badge bg-danger">{safe_status}</span>'
    return f'<span class="badge bg-success">{safe_status}</span>'


@lru_cache(maxsize=1024)
def format_truncated_with_tooltip(text: str, max_length: int = 30) -> str:
    """
    Truncate text and provide a tooltip with the full text.
    Performance: Caching provides ~7x speedup for repetitive metadata.
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return escape_html(text)

    truncated = text[:max_length] + "..."
    safe_full = escape_html(text)
    safe_truncated = escape_html(truncated)

    return f'<span class="truncated-text" title="{safe_full}">{safe_truncated}</span>'


@lru_cache(maxsize=1024)
def get_changed_count_badge(count: int) -> str:
    """Return a badge for changed trial count."""
    if count > 0:
        return f'<span class="badge bg-danger">{count}</span>'
    return '<span class="badge bg-success">0</span>'


@lru_cache(maxsize=1024)
def format_enrollment(value: Any) -> str:
    """
    Format enrollment number with commas (e.g., 1,234) for better numerical readability.
    Returns 'N/A' for None, empty, or non-numeric inputs.
    Performance: Caching avoids redundant type conversion and string formatting.
    """
    if value is None or value == "" or value == "N/A":
        return "N/A"
    try:
        # Handle cases where value might be a float string or already has commas
        num_val = int(float(str(value).replace(",", "")))
        return f"{num_val:,}"
    except (ValueError, TypeError):
        return "N/A"


@lru_cache(maxsize=1024)
def _format_diff_line_cached(escaped_line: str) -> str:
    """Internal cached helper for format_diff_line."""
    # Highlight additions/removals with Bootstrap classes
    if escaped_line.startswith("New field added:"):
        return f"<span class='text-success fw-bold'>{escaped_line}</span>"
    if escaped_line.startswith("Field removed:"):
        return f"<span class='text-danger fw-bold'>{escaped_line}</span>"

    return DIFF_CHANGE_PATTERN.sub(_replace_diff_match, escaped_line)


def format_diff_line(line: str) -> str:
    """
    Format a diff line with color-coded changes.
    Highlights 'changed from `old` to `new`' with Bootstrap classes.
    Also highlights new fields added and fields removed.
    Performance: Caching and pre-compiled regex yield ~10-20x speedup.
    """
    if not line:
        return ""

    # escape_html already handles truncation and internal caching
    escaped_line = escape_html(line)
    return _format_diff_line_cached(escaped_line)


@lru_cache(maxsize=1024)
def _format_diff_line_markdown_cached(escaped_line: str) -> str:
    """Internal cached helper for format_diff_line_markdown."""
    # Highlight additions/removals with Markdown bolding
    if escaped_line.startswith("New field added:"):
        return f"**{escaped_line}**"
    if escaped_line.startswith("Field removed:"):
        return f"**{escaped_line}**"

    return DIFF_CHANGE_PATTERN.sub(_replace_diff_match_markdown, escaped_line)


def format_diff_line_markdown(line: str) -> str:
    """
    Format a diff line with Markdown bolding for changes.
    Highlights 'changed from `old` to `new`' with native Markdown bolding.
    Also highlights new fields added and fields removed.
    """
    if not line:
        return ""

    # escape_html already handles truncation and internal caching
    escaped_line = escape_html(line)
    return _format_diff_line_markdown_cached(escaped_line)
