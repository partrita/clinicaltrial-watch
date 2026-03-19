import re
import html
from functools import lru_cache


@lru_cache(maxsize=1024)
def sanitize_id(identifier: str) -> str:
    """
    Sanitize an identifier (trial ID or target name) to prevent
    path traversal and code injection.
    Allows only alphanumeric characters, dashes, and underscores.
    """
    if not identifier:
        return "unknown"
    # Replace any non-alphanumeric, non-dash, non-underscore characters with an underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", str(identifier))
    # Remove leading/trailing underscores and prevent empty string
    sanitized = sanitized.strip("_")
    return sanitized if sanitized else "unknown"


def escape_html(text: str) -> str:
    """
    Escape HTML special characters in a string.
    Also explicitly escapes the pipe character '|' to prevent breaking Markdown tables.
    """
    if text is None:
        return ""
    escaped = html.escape(str(text))
    return escaped.replace("|", "&#124;")


def get_status_badge(status: str) -> str:
    """Return a Bootstrap badge for a trial status with emoji and ARIA label."""
    # Maps raw status to (display_label, emoji, bootstrap_class)
    status_configs = {
        "RECRUITING": ("Recruiting", "🟢", "success"),
        "ACTIVE_NOT_RECRUITING": ("Active (Not Recruiting)", "🔵", "info"),
        "COMPLETED": ("Completed", "⚪", "secondary"),
        "NOT_YET_RECRUITING": ("Not Yet Recruiting", "🟡", "warning"),
        "SUSPENDED": ("Suspended", "🟠", "danger"),
        "TERMINATED": ("Terminated", "🔴", "danger"),
        "WITHDRAWN": ("Withdrawn", "🔴", "danger"),
    }

    label, emoji, bg_class = status_configs.get(
        status, (status.replace("_", " ").title(), "⚪", "light text-dark")
    )

    safe_label = escape_html(label)
    safe_status = escape_html(status)
    display_text = f"{emoji} {safe_label}" if emoji else safe_label

    return (
        f'<span class="badge bg-{bg_class}" '
        f'title="Original status: {safe_status}" '
        f'aria-label="Status: {safe_label}">{display_text}</span>'
    )


def get_update_badge(monitor_status: str, last_change_date: str = None) -> str:
    """Return a badge/emoji for monitoring status with ARIA label and title."""
    safe_status = escape_html(monitor_status)
    title_extra = f". Last change: {escape_html(last_change_date)}" if last_change_date else ""
    if monitor_status == "Changed":
        return f'<span aria-label="Changes detected" title="Changes detected since last crawl{title_extra}">🔴 {safe_status}</span>'
    return f'<span aria-label="No recent changes" title="No changes detected since last crawl{title_extra}">🟢 {safe_status}</span>'


def format_truncated_with_tooltip(text: str, max_length: int = 30) -> str:
    """
    Truncate text and provide a tooltip with the full text.
    Uses 'truncated-text' class for styling and 'title' for accessibility.
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return escape_html(text)

    truncated = text[:max_length] + "..."
    safe_full = escape_html(text)
    # Truncate BEFORE escaping to avoid breaking entities
    safe_truncated = escape_html(truncated)

    return f'<span class="truncated-text" title="{safe_full}">{safe_truncated}</span>'


def get_changed_count_badge(count: int) -> str:
    """Return a badge for changed trial count with title."""
    if count > 0:
        return f'<span aria-label="{count} trials changed" title="{count} trials have updates">🔴 {count}</span>'
    return '<span aria-label="No trials changed" title="No trials have updates">🟢 0</span>'


def format_diff_line(line: str) -> str:
    """
    Format a diff line with color-coded additions/removals.
    Example: "Field `x` changed from `old` to `new`"
    """
    if not line:
        return ""

    # Escape HTML first
    safe_line = escape_html(line)

    # Highlight "from `value`" in red and "to `value`" in green
    # Pattern: changed from `(.*?)` to `(.*?)`
    pattern = r"(changed from `)(.*?)` (to `)(.*?)`"

    def replace_match(m):
        return (
            f"{m.group(1)}<span class='text-danger'>{m.group(2)}</span>` "
            f"{m.group(3)}<span class='text-success'>{m.group(4)}</span>`"
        )

    formatted = re.sub(pattern, replace_match, safe_line)

    # Also handle "New field added: `(.*?)`"
    formatted = re.sub(
        r"(New field added: `)(.*?)`",
        r"\1<span class='text-success'>\2</span>`",
        formatted,
    )

    # And "Field removed: `(.*?)`"
    formatted = re.sub(
        r"(Field removed: `)(.*?)`",
        r"\1<span class='text-danger'>\2</span>`",
        formatted,
    )

    return formatted
