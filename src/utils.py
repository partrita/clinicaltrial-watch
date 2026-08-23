import ast
import contextlib
import html
import os
import re
import ssl
import tempfile
from functools import lru_cache
from typing import Any

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
            return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

        def proxy_manager_for(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            kwargs["ssl_context"] = ctx
            return super().proxy_manager_for(*args, **kwargs)

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
MAX_CONFIG_SIZE = (
    10 * 1024 * 1024
)  # 10MB limit for local YAML/JSON config and data files
MAX_VALUE_LENGTH = 10000


def safe_str(obj: Any, max_length: int = MAX_VALUE_LENGTH) -> str:
    """
    Safely convert an object to a string, handling potential recursion errors
    and enforcing a maximum length (CWE-400).
    """
    try:
        s = str(obj)
    except RecursionError:
        return "[Complex Object: Too Deep]"
    return s[:max_length]


def safe_json_dumps(obj: Any, max_length: int = MAX_VALUE_LENGTH, **kwargs) -> str:
    """
    Safely convert an object to a JSON string, handling potential recursion errors
    and enforcing a maximum length (CWE-400).
    Note: Truncated JSON string may be invalid.
    """
    import json

    try:
        s = json.dumps(obj, **kwargs)
    except RecursionError:
        return '"[Complex Object: Too Deep]"'
    return s[:max_length]


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
DANGEROUS_CSV_CHARS = {
    "=",
    "+",
    "-",
    "@",
    ";",
    "%",
    "|",
    "\t",
    "\r",
    "\n",
    "\v",
    "\f",
    "\x1b",
    "`",
}


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

    # Limit identifier length before caching and handle recursion
    safe_identifier = safe_str(identifier, 255)
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
    text_str = safe_str(text, 65536)
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
        r"^[\s\x00-\x1f\u0080-\u009f\u00a0\u00ad\u034f\u1680\u200b-\u200f\u2028-\u202f\u205f\u2060-\u206f\u3000\uFEFF\u180b-\u180e\ufe00-\ufe0f\u115f\u1160\u3164\uffa0\u2800\U000E0020-\U000E007F]+",
        "",
        value,
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
    # Limit status string length before caching and handle recursion
    safe_status = safe_str(status, 255)
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

    # Limit phase string length before caching and handle recursion
    safe_phase = safe_str(phase, 255)
    return _get_phase_badge_cached(safe_phase)


@lru_cache(maxsize=1024)
def _get_update_badge_cached(
    monitor_status: str, last_change_date: str | None = None
) -> str:
    """Internal cached helper for get_update_badge."""
    safe_status = escape_html(monitor_status)
    title_attr = ""
    if last_change_date:
        safe_date = escape_html(last_change_date)
        title_attr = f' title="Last changed: {safe_date}"'

    if monitor_status == "Changed":
        return f'<span class="badge bg-danger"{title_attr}>{safe_status}</span>'
    return f'<span class="badge bg-success"{title_attr}>{safe_status}</span>'


def get_update_badge(monitor_status: str, last_change_date: str | None = None) -> str:
    """
    Return a badge for monitoring status.
    Truncates input BEFORE caching to prevent memory exhaustion DoS.
    """
    if not monitor_status:
        return ""

    # Limit string lengths before caching and handle recursion
    safe_status = safe_str(monitor_status, 255)
    safe_date = safe_str(last_change_date, 255) if last_change_date else None
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

    # Limit total text length before caching and handle recursion
    safe_text = safe_str(text, 10000)
    return _format_truncated_with_tooltip_cached(safe_text, max_length)


@lru_cache(maxsize=1024)
def get_changed_count_badge(count: int) -> str:
    """Return a badge for changed trial count."""
    safe_count = escape_html(safe_str(count))
    if count > 0:
        return f'<span class="badge bg-danger" aria-label="{safe_count} trials changed">{safe_count}</span>'
    return '<span class="badge bg-success" aria-label="0 trials changed">0</span>'


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

    # Limit string length before caching and handle recursion
    safe_value = safe_str(value, 255)
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

    # Limit line length before caching and handle recursion
    safe_line = safe_str(line, 10000)
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

    # Limit line length before caching and handle recursion
    safe_line = safe_str(line, 10000)
    return _format_diff_line_markdown_cached(safe_line)


# ---------------------------------------------------------------------------
# Human-readable diff rendering
# ---------------------------------------------------------------------------

# Korean labels for ClinicalTrials.gov protocol sections.
MODULE_LABELS: dict[str, str] = {
    "identificationModule": "기본 정보",
    "statusModule": "",
    "sponsorCollaboratorsModule": "스폰서",
    "conditionsModule": "적응증",
    "designModule": "",
    "armsInterventionsModule": "투약군·중재",
    "outcomesModule": "평가 지표",
    "contactsLocationsModule": "연구 기관",
    "eligibilityModule": "선정 기준",
    "descriptionModule": "상세 설명",
    "ipdSharingStatementModule": "IPD 공유 계획",
    "oversightModule": "감독 기관",
    "referencesModule": "참고 문헌",
    "protocolSection": "",
}

# Labels for well-known field paths (matched against the path suffix).
DIFF_FIELD_LABELS: dict[str, str] = {
    # statusModule
    "overallStatus": "모집 상태",
    "statusVerifiedDate": "상태 검증일",
    "startDateStruct.date": "시작일",
    "startDateStruct.type": "시작일 형식",
    "completionDateStruct.date": "종료 예정일",
    "completionDateStruct.type": "종료일 형식",
    "primaryCompletionDateStruct.date": "주 평가 종료 예정일",
    "primaryCompletionDateStruct.type": "주 평가 종료일 형식",
    "lastUpdateSubmitDate": "정보 제출일",
    "lastUpdatePostDateStruct.date": "정보 게시일",
    "lastUpdatePostDateStruct.type": "게시일 형식",
    "studyFirstSubmitDate": "최초 등록일",
    "studyFirstSubmitQCDate": "최초 등록 검수일",
    "studyFirstPostDateStruct.date": "최초 게시일",
    "studyFirstPostDateStruct.type": "최초 게시일 형식",
    "resultsFirstPostDateStruct.date": "결과 게시일",
    "resultsFirstPostDateStruct.type": "결과 게시일 형식",
    "whyStopped": "조기 종료 사유",
    "expandedAccessInfo.hasExpandedAccess": "확대 접근 여부",
    "eligibilityCriteria": "선정·제외 기준",
    "isFdaRegulatedDrug": "FDA 규제 의약품 여부",
    "isFdaRegulatedDevice": "FDA 규제 의료기기 여부",
    # identificationModule
    "briefTitle": "연구 제목(요약)",
    "officialTitle": "공식 연구 제목",
    "orgStudyIdInfo.primaryId": "기관 연구 ID",
    "nctId": "NCT ID",
    "organization.fullName": "등록 기관명",
    "organization.shortName": "등록 기관 약칭",
    # sponsorCollaboratorsModule
    "leadSponsor.name": "주관 기관",
    "leadSponsor.class": "주관 기관 유형",
    # designModule
    "phases": "임상 단계",
    "enrollmentInfo.count": "모집 인원",
    "enrollmentInfo.type": "모집 인원 기준",
    "studyType": "연구 유형",
    "designInfo.allocation": "배정 방식",
    "designInfo.interventionModel": "설계 모델",
    "designInfo.primaryPurpose": "연구 목적",
    "designInfo.maskingInfo.masking": "블라인딩",
}

# Labels for repeated list containers (rendered as "#N" rows).
LIST_CONTAINER_LABELS: dict[str, str] = {
    "locations": "연구 기관",
    "primaryOutcomes": "주 평가 지표",
    "secondaryOutcomes": "부가 평가 지표",
    "otherOutcomes": "기타 평가 지표",
    "interventions": "중재(약물)",
    "armGroups": "투약군",
    "conditions": "적응증",
    "collaborators": "협력 기관",
    "centralContacts": "담당자",
    "overallOfficials": "총괄 책임 연구자",
    "references": "참고 문헌",
    "keywords": "키워드",
}

# Labels for leaf keys inside list items or common generic leaves.
LEAF_FIELD_LABELS: dict[str, str] = {
    "city": "도시",
    "state": "주/지역",
    "country": "국가",
    "zip": "우편번호",
    "facility": "기관명",
    "status": "상태",
    "geoPoint.lat": "위도",
    "geoPoint.lon": "경도",
    "latitude": "위도",
    "longitude": "경도",
    "measure": "측정 항목",
    "timeFrame": "측정 시점",
    "description": "설명",
    "name": "이름",
    "label": "구분명",
    "title": "제목",
    "type": "유형",
    "class": "분류",
    "role": "역할",
    "affiliation": "소속",
    "contacts": "담당자",
    "phone": "전화",
    "email": "이메일",
    "firstName": "이름",
    "lastName": "성",
    "citation": "인용 문헌",
    "armGroupLabels": "투약군 구분",
    "interventionNames": "투여 약물",
    "sex": "성별 제한",
    "minimumAge": "최소 연령",
    "maximumAge": "최대 연령",
    "healthyVolunteers": "건강 자원자 포함",
    "briefSummary": "연구 요약",
    "detailedDescription": "연구 상세 설명",
}

# Korean labels for enum values frequently seen in diffs.
DIFF_VALUE_LABELS: dict[str, str] = {
    "RECRUITING": "모집 중",
    "ACTIVE_NOT_RECRUITING": "진행 중(비모집)",
    "ENROLLING_BY_INVITATION": "초청 모집",
    "NOT_YET_RECRUITING": "모집 예정",
    "COMPLETED": "완료",
    "SUSPENDED": "일시중단",
    "TERMINATED": "조기종료",
    "WITHDRAWN": "철회",
    "NO_LONGER_AVAILABLE": "더 이상 이용 불가",
    "AVAILABLE": "이용 가능",
    "ENROLLING_BY_INVITATION_ONLY": "초청 모집",
    "UNKNOWN": "알 수 없음",
    "PHASE1": "1상",
    "PHASE2": "2상",
    "PHASE3": "3상",
    "PHASE4": "4상",
    "EARLY_PHASE1": "초기 1상",
    "PHASE2/PHASE3": "2상/3상",
    "PHASE1/PHASE2": "1상/2상",
    "PHASE3/PHASE4": "3상/4상",
    "NOT_APPLICABLE": "해당 없음",
    "OBSERVATIONAL": "관찰 연구",
    "INTERVENTIONAL": "중재 연구",
    "EXPANDED_ACCESS": "확대 접근",
}

# Keys preferred when summarizing dict-like values.
_SUMMARY_KEYS = ("measure", "name", "facility", "label", "title", "id", "condition")

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Patterns for records produced by diff_engine.format_diff().
# Values may contain newlines (e.g. long descriptions), so records are split
# on their line-start boundary first and then matched with DOTALL.
_DIFF_RECORD_SPLIT_RE = re.compile(
    r"(?=^(?:Field `|New field added:|Field removed:))", re.MULTILINE
)
_DIFF_CHANGED_RE = re.compile(
    r"\AField `([^`]*)` changed from `(.*?)` to `(.*)`\Z", re.DOTALL
)
_DIFF_ADDED_RE = re.compile(r"\ANew field added: `(.*)`\Z", re.DOTALL)
_DIFF_REMOVED_RE = re.compile(r"\AField removed: `(.*)`\Z", re.DOTALL)
_DIFF_FALLBACK_RE = re.compile(r"\A([^:`]*)`: `(.*?)` -> `(.*)`\Z", re.DOTALL)

# Token like "8", "39", or "39city" (index possibly glued to the next key),
# produced after bracket-stripping normalization of DeepDiff list paths.
_DIFF_INDEX_TOKEN_RE = re.compile(r"\A(\d+)(.*)\Z")


def _truncate_middle(text: str, max_length: int) -> str:
    """Truncate text with an ellipsis, keeping head and tail visible."""
    if max_length <= 1 or len(text) <= max_length:
        return text
    keep = max(max_length - 1, 0)
    head = keep - keep // 2
    tail = keep // 2
    return text[:head] + "…" + (text[len(text) - tail :] if tail else "")


def _prettify_token(token: str) -> str:
    """Turn a camelCase token into a spaced, capitalized phrase."""
    pretty = _CAMEL_SPLIT_RE.sub(" ", token)
    return pretty[:1].upper() + pretty[1:]


def _lookup_leaf_label(leaf_tokens: list[str]) -> str:
    """Match the longest known field-path suffix against the label maps."""
    max_suffix = min(len(leaf_tokens), 3)
    for k in range(max_suffix, 0, -1):
        candidate = ".".join(leaf_tokens[-k:])
        if candidate in DIFF_FIELD_LABELS:
            return DIFF_FIELD_LABELS[candidate]
    for k in range(max_suffix, 0, -1):
        candidate = ".".join(leaf_tokens[-k:])
        if candidate in LEAF_FIELD_LABELS:
            return LEAF_FIELD_LABELS[candidate]
    return ""


def _prettify_leaf_fallback(leaf_tokens: list[str]) -> str:
    """Prettify unknown leaf tokens into a readable phrase."""
    fallback_parts = []
    for t in leaf_tokens[-2:]:
        stripped = t.removesuffix("Module")
        fallback_parts.append(_prettify_token(stripped))
    return " · ".join(fallback_parts)


def humanize_diff_field(path: str) -> str:
    """
    Convert a raw JSON path from a diff record into a human-readable
    Korean label.

    Examples:
        statusModule.overallStatus                      -> 모집 상태
        designModule.enrollmentInfo.count               -> 모집 인원
        contactsLocationsModule.locations.[39]city      -> 연구 기관 #40 · 도시
        contactsLocationsModule.locations.[19]contacts.[0]phone
                                                        -> 연구 기관 #20 · 담당자 #1 · 전화
        outcomesModule.primaryOutcomes.[0]              -> 주 평가 지표 #1

    Unknown paths fall back to prettified camelCase tokens so that they are
    still readable instead of showing raw JSON paths.
    """
    if not path:
        return ""

    raw = safe_str(path, 255).strip()
    # Normalize DeepDiff-style paths into dot-separated tokens.
    # Handles both `root['a']['b'][8]['c']` and cleaned forms like
    # `a.b.[39]city` / `a.b.8` produced by diff_engine.format_diff().
    raw = raw.removeprefix("root")
    raw = raw.replace("['", ".").replace("']", "")
    raw = raw.replace("[", ".").replace("]", "")
    tokens = [t for t in raw.split(".") if t and t != "root"]
    if not tokens:
        return safe_str(path, 80)

    module_label = ""
    if tokens[0] in MODULE_LABELS:
        module_label = MODULE_LABELS[tokens[0]]
        tokens = tokens[1:]

    container_label = ""
    item_index: int | None = None
    leaf_tokens: list[str] = []
    chain: list[str] = []

    for tok in tokens:
        idx_match = _DIFF_INDEX_TOKEN_RE.match(tok)
        if idx_match is not None:
            idx = int(idx_match.group(1))
            rest = idx_match.group(2)
            if leaf_tokens:
                # Index applies to the nested list named by the pending
                # leaf tokens (e.g. `contacts` inside one location).
                nested_name = _lookup_leaf_label(
                    leaf_tokens
                ) or _prettify_leaf_fallback(leaf_tokens)
                chain.append(f"{nested_name} #{idx + 1}")
                leaf_tokens = []
            elif item_index is None:
                item_index = idx
            elif chain:
                # Rare extra index without an intervening key; renumber the
                # last chain entry instead of dropping it.
                head = chain[-1].rsplit(" #", 1)[0]
                chain[-1] = f"{head} #{idx + 1}"
            if rest:
                leaf_tokens.append(rest)
            continue
        if tok in LIST_CONTAINER_LABELS:
            if item_index is None and not chain:
                container_label = LIST_CONTAINER_LABELS[tok]
            else:
                # Nested container appearing after indexing; resolve it as a
                # regular (unknown) leaf via the chain mechanism.
                leaf_tokens.append(tok)
            continue
        leaf_tokens.append(tok)

    parts: list[str] = []
    if container_label:
        parts.append(
            f"{container_label} #{item_index + 1}"
            if item_index is not None
            else container_label
        )
    parts.extend(chain)

    leaf_label = _lookup_leaf_label(leaf_tokens)
    if leaf_label:
        parts.append(leaf_label)
    elif leaf_tokens:
        parts.append(_prettify_leaf_fallback(leaf_tokens))

    if not parts and tokens:
        label = _prettify_token(tokens[-1])
    else:
        label = " · ".join(parts) if parts else (module_label or safe_str(path, 80))
    # Only add module context when there is no specific container/leaf label.
    if module_label and not container_label and not leaf_label and not chain and parts:
        label = f"{module_label} · {label}"
    return label


def _humanize_scalar(text: str) -> str:
    upper = text.strip().upper()
    if upper in DIFF_VALUE_LABELS:
        return f"{DIFF_VALUE_LABELS[upper]} ({text.strip()})"
    return text


def humanize_diff_value(raw: Any, max_length: int = 120) -> str:
    """
    Convert a raw diff value into a short, human-readable string.

    - Dict-like values (e.g. whole outcome objects) are summarized using a
      representative key such as 'measure'.
    - List-like values are joined with commas.
    - Known enums (statuses, phases) get Korean labels.
    - Long values are truncated with an ellipsis.
    """
    if raw is None:
        return ""
    # Normalize all whitespace (incl. newlines) so values render safely
    # inside Markdown tables and bullet lists.
    text = " ".join(safe_str(raw, MAX_VALUE_LENGTH).split())
    if not text:
        return ""

    # Try to parse Python-repr style containers.
    if text[0] in "{[" and text[-1] in "}]":
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            parsed = None
        if isinstance(parsed, dict):
            for key in _SUMMARY_KEYS:
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return _truncate_middle(value.strip(), max_length)
            try:
                compact = ", ".join(
                    f"{k}: {_truncate_middle(str(v), 40)}"
                    for k, v in list(parsed.items())[:4]
                )
                return _truncate_middle(compact, max_length)
            except (TypeError, ValueError, RecursionError):
                return _truncate_middle(text, max_length)
        if isinstance(parsed, (list, tuple)):
            items = [_humanize_scalar(str(v)) for v in parsed[:6]]
            joined = ", ".join(items)
            if len(parsed) > 6:
                joined += f" …({len(parsed)}개)"
            return _truncate_middle(joined, max_length)

    # Values may have been truncated during storage (e.g. 1000-char cap),
    # making literal_eval fail. Fall back to regex extraction of a
    # representative key so we still show something meaningful.
    if text[0] == "{":
        for key in _SUMMARY_KEYS:
            m = re.search(rf"'{key}':\s*['\"]((?:[^'\"]|\\.)*)['\"]", text)
            if m:
                value = (
                    m.group(1)
                    .replace("\\'", "'")
                    .replace('\\"', '"')
                    .replace("\\n", " ")
                    .strip()
                )
                if value:
                    return _truncate_middle(value, max_length)

    return _truncate_middle(_humanize_scalar(text), max_length)


def parse_diff_records(diff_text: str) -> list[dict[str, str]]:
    """
    Parse the plain-text diff stored in history JSON files into structured
    change records.

    Returns a list of dicts with keys:
        kind:  'changed' | 'added' | 'removed' | 'fallback'
        field: raw field path
        old / new: raw values ('' when not applicable)
    Unrecognized lines are returned as {'kind': 'raw', 'text': ...}.
    """
    if not diff_text:
        return []

    text = safe_str(diff_text, 100000)
    segments = _DIFF_RECORD_SPLIT_RE.split(text)
    records: list[dict[str, str]] = []

    for segment in segments:
        segment = segment.strip()
        if not segment or segment == "Initial data collection":
            continue

        m = _DIFF_CHANGED_RE.match(segment)
        if m:
            records.append(
                {
                    "kind": "changed",
                    "field": m.group(1),
                    "old": m.group(2),
                    "new": m.group(3),
                }
            )
            continue

        m = _DIFF_ADDED_RE.match(segment)
        if m:
            records.append({"kind": "added", "field": m.group(1), "old": "", "new": ""})
            continue

        m = _DIFF_REMOVED_RE.match(segment)
        if m:
            records.append(
                {"kind": "removed", "field": m.group(1), "old": "", "new": ""}
            )
            continue

        m = _DIFF_FALLBACK_RE.match(segment)
        if m:
            records.append(
                {
                    "kind": "changed",
                    "field": m.group(1),
                    "old": m.group(2),
                    "new": m.group(3),
                }
            )
            continue

        records.append({"kind": "raw", "field": "", "old": "", "new": segment})

    return records


# ---------------------------------------------------------------------------
# History rendering (human-readable change tables)
# ---------------------------------------------------------------------------

DIFF_KIND_ICONS: dict[str, str] = {
    "changed": "✏️",
    "added": "➕",
    "removed": "➖",
    "raw": "ℹ️",
}

_DIFF_TS_SAFE_RE = re.compile(r"[^0-9A-Za-z: .\-]")

# Patterns for feed events written by main.update_target_history().
_FEED_MORE_RE = re.compile(r"\s*\(and (\d+) more\)\Z")
_FEED_CHANGES_RE = re.compile(r"\AChanges detected in (\d+) trials?: (.*)\Z", re.DOTALL)
_FEED_INITIAL_RE = re.compile(r"\AInitial data collection: (\d+) trials found\.?\Z")


def safe_timestamp(value: Any) -> str:
    """
    Sanitize a history timestamp for display (keeps date/time chars only,
    so colons stay readable instead of being HTML-escaped).
    """
    text = str(value or "").strip()
    cleaned = _DIFF_TS_SAFE_RE.sub("", text)[:16].strip()
    return cleaned if cleaned else "-"


def humanize_feed_event(event: Any) -> str:
    """
    Translate a target-level feed event into Korean for display.

    Storage keeps the original English messages; translation happens at
    render time so that existing history files remain readable too.
    Unrecognized texts are returned unchanged.
    """
    if event is None:
        return "-"
    text = safe_str(event, 2000).strip()
    if not text:
        return ""

    more_count = None
    more_match = _FEED_MORE_RE.search(text)
    if more_match:
        more_count = more_match.group(1)
        text = text[: more_match.start()].rstrip()

    translated = ""
    m = _FEED_CHANGES_RE.match(text)
    if m:
        translated = f"{m.group(1)}개 임상에서 변경 감지: {m.group(2)}"
    else:
        m2 = _FEED_INITIAL_RE.match(text)
        if m2:
            translated = f"최초 데이터 수집: {m2.group(1)}개 임상"

    if not translated:
        return safe_str(event, 2000).strip() or "-"
    if more_count:
        translated += f" (외 {more_count}건)"
    return translated


def format_diff_cell(value: Any, max_length: int = 90) -> str:
    """
    Escape and truncate a diff value for a Markdown table cell.
    Literal newlines would break Markdown tables, so whitespace is collapsed;
    over-long values get an HTML tooltip with the full flattened text.
    """
    if not value:
        return "-"
    flat = " ".join(str(value).split())
    shown = flat if len(flat) <= max_length else flat[:max_length] + "…"
    cell = escape_html(shown)
    if len(flat) > max_length:
        # Title attribute needs plain HTML escaping only (no Markdown rules).
        tooltip = html.escape(flat, quote=True)
        cell = f'<span class="truncated-text" title="{tooltip}">{cell}</span>'
    return cell


def collect_history_events(history: Any) -> list[tuple[str, list[dict[str, str]]]]:
    """
    Parse a trial history JSON payload into (timestamp, records) pairs,
    skipping non-dict entries and the initial data-collection marker.
    Order is preserved as stored (oldest first).
    """
    events: list[tuple[str, list[dict[str, str]]]] = []
    if not isinstance(history, list):
        return events
    for r in history:
        if not isinstance(r, dict):
            continue
        diff_text = str(r.get("diff", ""))
        if diff_text == "Initial data collection":
            continue
        recs = parse_diff_records(diff_text)
        if recs:
            events.append((safe_timestamp(r.get("timestamp")), recs))
    return events


def _summarize_change_counts(recs: list[dict[str, str]]) -> str:
    """Summarize change records as '변경 N건, 추가 M건, 삭제 K건'."""
    n_changed = sum(1 for x in recs if x["kind"] == "changed")
    n_added = sum(1 for x in recs if x["kind"] == "added")
    n_removed = sum(1 for x in recs if x["kind"] == "removed")
    parts = []
    if n_changed:
        parts.append(f"변경 {n_changed}건")
    if n_added:
        parts.append(f"추가 {n_added}건")
    if n_removed:
        parts.append(f"삭제 {n_removed}건")
    return ", ".join(parts) if parts else f"{len(recs)}건"


def _format_change_table(recs: list[dict[str, str]]) -> list[str]:
    """Render parsed diff records as a Markdown table of 항목/이전 값/변경 후 값."""
    lines = ["| 구분 | 항목 | 이전 값 | 변경 후 값 |", "| :-- | --- | --- | --- |"]
    for rec in recs:
        kind = rec.get("kind", "raw")
        icon = DIFF_KIND_ICONS.get(kind, "ℹ️")
        label = humanize_diff_field(rec.get("field", ""))
        if kind == "added":
            old_cell, new_cell = "-", "새로 추가됨"
        elif kind == "removed":
            old_cell, new_cell = "삭제됨", "-"
        elif kind == "raw":
            old_cell, new_cell = "-", format_diff_cell(str(rec.get("new", "")))
        else:
            old_h = humanize_diff_value(rec.get("old"))
            new_h = humanize_diff_value(rec.get("new"))
            old_cell = format_diff_cell(old_h)
            new_cell = format_diff_cell(new_h)
            if old_h == new_h and old_h and old_h != "-":
                # Raw values differ but summarize to the same label
                # (e.g. only a long description inside an object changed).
                new_cell += (
                    ' <span class="text-muted"><small>(세부 내용 변경)</small></span>'
                )
        lines.append(
            f"| {icon} | {escape_html(label) or '-'} | {old_cell} | {new_cell} |"
        )
    return lines


def _render_event_blocks(
    events: list[tuple[str, list[dict[str, str]]]],
    max_events: int | None = None,
    heading_level: int | None = 3,
) -> str:
    """Render collected events newest-first as Markdown sections."""
    if max_events is not None:
        events = events[-max_events:]
    blocks: list[str] = []
    for timestamp, recs in reversed(events):
        summary = _summarize_change_counts(recs)
        header = (
            f"{'#' * heading_level} 📅 {timestamp} · {summary}"
            if heading_level
            else f"**📅 {timestamp} · {summary}**"
        )
        blocks.append("\n".join([header, ""] + _format_change_table(recs) + [""]))
    return "\n".join(blocks)


def render_history_sections(
    history: Any,
    max_events: int | None = None,
    heading_level: int | None = 3,
) -> str:
    """
    Render history records as human-readable Markdown change sections.

    Each detection time becomes one section: a dated heading with a change
    summary followed by a table of 항목 / 이전 값 / 변경 후 값.
    Returns an empty string when there is nothing to show.
    """
    return _render_event_blocks(
        collect_history_events(history), max_events, heading_level
    )


def render_trial_history_body(history: Any, trial_id: str) -> str:
    """
    Render a full trial history page body with an event-count header,
    or a friendly message when no changes were recorded yet.
    """
    events = collect_history_events(history)
    if not events:
        return f"아직 {trial_id}에 대한 변경 기록이 없습니다."
    header = [f"## 🕘 변경 이력 ({len(events)}회)", ""]
    return "\n".join(header) + "\n" + _render_event_blocks(events)


def create_safe_session(
    user_agent: str, max_retries: int = 2, pool_size: int = 10
) -> Any | None:
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
    filepath: str,
    mode: str = "w",
    encoding: str = "utf-8",
    newline: str | None = None,
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

        # After successfully closing the context, preserve original permissions (CWE-732)
        if os.path.exists(filepath):
            try:
                mode = os.stat(filepath).st_mode & 0o777
                os.chmod(tmppath, mode)
            except OSError:
                # Fallback for systems that might not support chmod on temp files
                pass

        # Replace the original file with the new one
        os.replace(tmppath, filepath)
    except Exception:
        # If any error occurred, try to remove the temporary file
        if tmppath and os.path.exists(tmppath):
            try:
                os.remove(tmppath)
            except OSError:
                pass
        raise
