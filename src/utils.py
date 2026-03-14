import re
import html


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
    """Return a Bootstrap badge for a trial status."""
    status_map = {
        "RECRUITING": "success",
        "ACTIVE_NOT_RECRUITING": "info",
        "COMPLETED": "secondary",
        "NOT_YET_RECRUITING": "warning",
        "SUSPENDED": "danger",
        "TERMINATED": "danger",
        "WITHDRAWN": "danger",
    }
    badge_class = status_map.get(status, "light text-dark")
    safe_status = escape_html(status)
    return f'<span class="badge bg-{badge_class}">{safe_status}</span>'


def get_update_badge(monitor_status: str) -> str:
    """Return a badge/emoji for monitoring status with ARIA label."""
    if monitor_status == "Changed":
        return f'<span aria-label="Changes detected">🔴 {escape_html(monitor_status)}</span>'
    return f'<span aria-label="No recent changes">🟢 {escape_html(monitor_status)}</span>'


def get_changed_count_badge(count: int) -> str:
    """Return a badge for changed trial count."""
    if count > 0:
        return f'<span aria-label="{count} trials changed">🔴 {count}</span>'
    return '<span aria-label="No trials changed">🟢 0</span>'
