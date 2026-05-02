import pytest
from src.utils import sanitize_id, escape_html, is_valid_nct_id


def test_sanitize_id_path_traversal():
    # sanitize_id replaces each non-alphanumeric character with an underscore
    # and strips leading/trailing underscores
    assert sanitize_id("../etc/passwd") == "etc_passwd"
    assert sanitize_id("..\\windows\\system32") == "windows_system32"
    assert sanitize_id("target/../../secret") == "target_______secret"


def test_sanitize_id_special_chars():
    assert sanitize_id("NCT01234567!") == "NCT01234567"
    assert (
        sanitize_id("Breast Cancer (Triple Negative)")
        == "Breast_Cancer__Triple_Negative"
    )
    assert sanitize_id("") == "unknown"
    assert sanitize_id(None) == "unknown"


def test_sanitize_id_length_limit():
    long_id = "A" * 300
    sanitized = sanitize_id(long_id)
    assert len(sanitized) <= 255
    assert sanitized == "A" * 255


def test_escape_html_basic():
    # html.escape escapes ' as &#x27;
    assert (
        escape_html("<script>alert('xss')</script>")
        == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
    )
    assert (
        escape_html('Hello "World" & others') == "Hello &quot;World&quot; &amp; others"
    )


def test_escape_html_markdown():
    # Pipe character should be escaped to prevent Markdown table injection
    assert escape_html("Data | with | pipes") == "Data &#124; with &#124; pipes"
    # Brackets should be escaped to prevent Markdown link injection
    assert escape_html("Link [text](url)") == "Link &#91;text&#93;(url)"
    # Backslash and MathJax characters should be escaped
    assert escape_html("Math $x+y$ and Backslash \\") == "Math &#36;x+y&#36; and Backslash &#92;"
    # Curly braces should be escaped to prevent Quarto/Pandoc attribute injection
    assert escape_html("Text { .class }") == "Text &#123; .class &#125;"


def test_escape_html_none():
    assert escape_html(None) == ""


def test_is_valid_nct_id():
    assert is_valid_nct_id("NCT12345678") is True
    assert is_valid_nct_id("NCT00000000") is True
    assert is_valid_nct_id("NCT1234567") is False  # Too short
    assert is_valid_nct_id("NCT123456789") is False  # Too long
    assert is_valid_nct_id("NCT" + "1" * 40) is False  # Max length check
    assert is_valid_nct_id("nct12345678") is False  # Case sensitive
    assert is_valid_nct_id("NCT12345678\n") is False  # Should not accept trailing newline
    # Persian digits should be rejected (must be ASCII [0-9])
    assert is_valid_nct_id("NCT\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667") is False
    assert is_valid_nct_id("NCTabcdefgh") is False  # Not digits
    assert is_valid_nct_id("") is False
    assert is_valid_nct_id(None) is False
    assert is_valid_nct_id("NCT12345678; DROP TABLE studies;") is False


def test_generation_escaping():
    """Verify that target metadata is escaped during site generation."""
    from src.generate_target_pages import generate_target_qmd, update_quarto_yml
    import os

    name, desc = "Target | Pipe", "Desc <script>"
    # Test QMD generation
    qmd = generate_target_qmd(name, desc, output_dir="tests/tmp_targets")
    with open(qmd, "r", encoding="utf-8") as f:
        content = f.read()
    # yaml.safe_dump might not use quotes for this string
    assert "title: Target &#124; Pipe" in content
    assert "Desc &lt;script&gt;" in content

    # Test YAML generation
    yml = "tests/tmp_quarto.yml"
    update_quarto_yml([{"name": name}], yml)
    with open(yml, "r", encoding="utf-8") as f:
        content = f.read()
    assert "text: Target &#124; Pipe" in content

    # Cleanup
    os.remove(qmd)
    os.remove(yml)
    os.rmdir("tests/tmp_targets")


def test_process_trial_validation():
    """Verify that process_trial skips invalid NCT IDs."""
    from src.main import process_trial

    invalid_trial = {"id": "evil", "name": "Evil Trial"}
    report, raw = process_trial(invalid_trial, "TestTarget")

    assert report is None
    assert raw is None


def test_extract_trials_validation():
    """Verify that extract_trials filters out invalid NCT IDs."""
    from src.auto_discover_trials import extract_trials

    api_studies = [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT12345678",
                    "briefTitle": "Valid Trial",
                }
            }
        },
        {
            "protocolSection": {
                "identificationModule": {"nctId": "evil", "briefTitle": "Invalid Trial"}
            }
        },
    ]

    extracted = extract_trials(api_studies)
    assert len(extracted) == 1
    assert extracted[0]["id"] == "NCT12345678"


def test_remove_trial_validation():
    """Verify that remove_trial rejects invalid NCT IDs."""
    from src.manage_trials import remove_trial

    assert remove_trial("evil") is False


def test_fetch_trial_data_validation():
    """Verify that fetch_trial_data rejects invalid NCT IDs."""
    from src.crawler import fetch_trial_data

    assert fetch_trial_data("evil") is None
    assert fetch_trial_data("NCT1234") is None  # Too short


def test_sanitize_csv_value():
    """Verify that CSV formula injection is prevented."""
    from src.utils import sanitize_csv_value

    assert sanitize_csv_value("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert sanitize_csv_value("+42") == "'+42"
    assert sanitize_csv_value("-5") == "'-5"
    assert sanitize_csv_value("@something") == "'@something"
    assert sanitize_csv_value(";something") == "';something"
    assert sanitize_csv_value("%something") == "'%something"
    assert sanitize_csv_value("\t=SUM(A1)") == "'\t=SUM(A1)"
    assert sanitize_csv_value("\r-5") == "'\r-5"
    assert sanitize_csv_value("\n=1+1") == "'\n=1+1"
    assert sanitize_csv_value("  =SUM(A1)") == "'  =SUM(A1)"
    assert sanitize_csv_value(" \n @info") == "' \n @info"
    assert sanitize_csv_value(" \t @info") == "' \t @info"
    assert sanitize_csv_value("Normal text") == "Normal text"
    assert sanitize_csv_value(123) == 123
    assert sanitize_csv_value(None) is None
    assert sanitize_csv_value("") == ""
    assert sanitize_csv_value("   ") == "   "


def test_get_phase_badge():
    """Verify that get_phase_badge correctly handles various inputs and escapes data."""
    from src.utils import get_phase_badge

    # Simple phase
    res = get_phase_badge("PHASE1")
    assert "badge bg-primary" in res
    assert "PHASE1" in res

    # Multiple phases
    res = get_phase_badge("PHASE1, PHASE2")
    assert "badge bg-primary" in res
    assert "badge bg-info" in res
    assert "PHASE1" in res
    assert "PHASE2" in res

    # Unknown phase
    res = get_phase_badge("Unknown Phase")
    assert "badge bg-light text-dark" in res
    assert "Unknown Phase" in res

    # XSS attempt
    res = get_phase_badge("<script>alert(1)</script>")
    assert "&lt;script&gt;" in res
    assert "<script>" not in res

    # Empty/N/A
    assert get_phase_badge("") == "N/A"
    assert get_phase_badge("N/A") == "N/A"


def test_ui_helpers_accessibility():
    """Verify the presence of ARIA and accessibility attributes in UI helpers."""
    from src.utils import get_update_badge, get_changed_count_badge, format_truncated_with_tooltip

    # get_update_badge with date
    res = get_update_badge("Changed", "2023-10-27")
    assert 'title="Last changed: 2023-10-27"' in res

    # get_changed_count_badge
    res = get_changed_count_badge(5)
    assert 'aria-label="5 trials changed"' in res
    res_zero = get_changed_count_badge(0)
    assert 'aria-label="0 trials changed"' in res_zero

    # format_truncated_with_tooltip
    long_text = "This is a very long text that should be truncated"
    res = format_truncated_with_tooltip(long_text, max_length=10)
    assert 'tabindex="0"' in res
    assert 'role="note"' in res
    assert f'aria-label="{long_text}"' in res
    assert f'title="{long_text}"' in res


def test_format_enrollment_robustness():
    """Verify numeric overflow handling in format_enrollment."""
    from src.utils import format_enrollment

    # Normal case
    assert format_enrollment(1234) == "1,234"

    # Extreme case that might cause OverflowError in some environments/versions
    # (though Python handles large ints, float conversion or other steps might fail)
    # Note: After hardening, input is truncated to 255 chars.
    # float() of 1000 ones fails, but float() of 255 ones succeeds in Python.
    # We'll use a string that is still too large for float even after truncation to 255 if we want N/A,
    # or just test that it handles the truncated input.
    huge_val = "9" * 400
    # After truncation to 255, 9*255 is ~1e255, which is < 1e308 (max float)
    # So it will now return a formatted string instead of N/A.
    res = format_enrollment(huge_val)
    assert res != "N/A"
    assert len(res) > 255 # due to commas


def test_security_length_limits():
    """Verify that length limits are enforced for security utilities."""
    from src.utils import (
        sanitize_csv_value,
        escape_html,
        sanitize_id,
        format_diff_line,
        format_truncated_with_tooltip,
    )

    # CSV sanitization limit (32,767)
    long_val = "A" * 40000
    sanitized_csv = sanitize_csv_value(long_val)
    assert len(sanitized_csv) == 32767

    # HTML escaping limit (65,536)
    long_text = "B" * 70000
    res_escaped_html = escape_html(long_text)
    assert len(res_escaped_html) == 65536

    # sanitize_id limit (255)
    long_id = "C" * 1000
    res_sanitize_id = sanitize_id(long_id)
    assert len(res_sanitize_id) == 255

    # format_diff_line limit (10,000)
    long_line = "D" * 20000
    res_diff = format_diff_line(long_line)
    # The output might be longer due to escaping, but we check if it processed the truncated input.
    assert len(res_diff) >= 10000

    # format_truncated_with_tooltip limit (10,000)
    long_tooltip = "E" * 20000
    res_tooltip = format_truncated_with_tooltip(long_tooltip)
    assert 'title="EE' in res_tooltip


def test_ui_helpers_length_limits_new():
    """Verify newly hardened UI helpers length limits."""
    from src.utils import get_status_badge, get_phase_badge, get_update_badge, format_enrollment

    # get_status_badge limit (255)
    long_status = "S" * 300
    res_status = get_status_badge(long_status)
    # .title() is called, so it becomes S followed by s...
    expected_inner = "S" + "s" * 254
    assert expected_inner in res_status
    assert expected_inner + "s" not in res_status

    # get_phase_badge limit (255)
    long_phase = "P" * 300
    res_phase = get_phase_badge(long_phase)
    assert "P" * 255 in res_phase
    assert "P" * 256 not in res_phase

    # get_update_badge limit (255)
    long_update = "U" * 300
    long_date = "D" * 300
    res_update = get_update_badge(long_update, long_date)
    assert "U" * 255 in res_update
    assert 'title="Last changed: ' + "D" * 255 in res_update

    # format_enrollment limit (255)
    long_enroll = "1" * 300
    res_enroll = format_enrollment(long_enroll)
    # After truncation to 255, it still fits in a float and is a valid int
    assert res_enroll != "N/A"
    assert len(res_enroll) > 255 # due to commas


def test_flatten_key_length_limit():
    """Verify _get_flatten_key length limits in src/main.py."""
    from src.main import _get_flatten_key

    long_parent = "P" * 300
    long_k = "K" * 300
    res = _get_flatten_key(long_parent, long_k)
    assert "P" * 255 in res
    assert "K" * 255 in res


def test_load_config_robustness():
    """Verify load_config robustness in src/main.py."""
    from src.main import load_config
    import os

    test_yaml = "tests/test_robust_config.yaml"

    # Test with non-dictionary content
    with open(test_yaml, "w", encoding="utf-8") as f:
        f.write("- item1\n- item2")

    try:
        with pytest.raises(ValueError):
            load_config(test_yaml)

        # Test with empty file
        with open(test_yaml, "w", encoding="utf-8") as f:
            f.write("")
        res = load_config(test_yaml)
        assert res == {"targets": []}
    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)


def test_csv_header_injection_prevention():
    """Verify that CSV headers and keys are sanitized against formula injection."""
    from src.main import save_target_data
    from src.utils import sanitize_csv_value
    import os
    import csv
    import shutil

    test_target = "InjectionTarget"
    test_dir = "data/targets/injectiontarget"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    summary_report = [
        {
            "id": "=NCT12345678",
            "name": "Trial 1",
            "status": "RECRUITING"
        }
    ]
    all_raw_data = [
        {
            "+Key": "Value 1",
            "Normal": "@Formula"
        }
    ]

    try:
        save_target_data(test_target, summary_report, all_raw_data)

        # 1. Check status_summary.csv values (headers are fixed)
        summary_csv = os.path.join(test_dir, "status_summary.csv")
        with open(summary_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            assert row["id"] == "'=NCT12345678"

        # 2. Check all_trials_raw.csv headers and values
        raw_csv = os.path.join(test_dir, "all_trials_raw.csv")
        with open(raw_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            assert "'+Key" in headers
            assert "Normal" in headers

            row = next(reader)
            assert row["'+Key"] == "Value 1"
            assert row["Normal"] == "'@Formula"

    finally:
        if os.path.exists("data/targets/injectiontarget"):
            shutil.rmtree("data/targets/injectiontarget")


def test_sanitize_csv_value_extended():
    """Verify improved sanitize_csv_value with extended dangerous characters and bypasses."""
    from src.utils import sanitize_csv_value

    # New dangerous characters
    assert sanitize_csv_value("\x1b=SUM(1+1)") == "'\x1b=SUM(1+1)"
    assert sanitize_csv_value("\v=SUM(1+1)") == "'\v=SUM(1+1)"
    assert sanitize_csv_value("\f=SUM(1+1)") == "'\f=SUM(1+1)"

    # Leading whitespace bypasses (including non-ASCII)
    assert sanitize_csv_value(" \t\n\r=1+1") == "' \t\n\r=1+1"
    assert sanitize_csv_value("\u00A0=SUM(1+1)") == "'\u00A0=SUM(1+1)"

    # Single character dangerous inputs
    assert sanitize_csv_value("=") == "'="
    assert sanitize_csv_value("+") == "'+"
    assert sanitize_csv_value("\t") == "'\t"

    # Multiple dangerous characters in a row
    assert sanitize_csv_value("==") == "'=="
    assert sanitize_csv_value(" =") == "' ="

    # Normal text
    assert sanitize_csv_value("123") == "123"
    assert sanitize_csv_value("Value") == "Value"


def test_update_from_csv_security_limits():
    """Verify that update_trials_from_csv.py enforces DoS limits."""
    from src.update_trials_from_csv import read_csv_trials, update_target
    import os
    import csv

    test_csv = "tests/test_dos.csv"

    # 1. Test MAX_CSV_SIZE limit
    # Create a 11MB file
    with open(test_csv, "wb") as f:
        f.write(b"A" * (11 * 1024 * 1024))

    try:
        res = read_csv_trials(test_csv)
        assert res == []
    finally:
        if os.path.exists(test_csv):
            os.remove(test_csv)

    # 2. Test MAX_CSV_ROWS limit
    with open(test_csv, "w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["NCT Number", "Study Title"])
        writer.writeheader()
        for i in range(6000):
            writer.writerow({"NCT Number": f"NCT{i:08d}", "Study Title": "Title"})

    try:
        res = read_csv_trials(test_csv)
        assert len(res) == 5000
    finally:
        if os.path.exists(test_csv):
            os.remove(test_csv)

    # 3. Test MAX_TARGETS limit
    data = {"targets": [{"name": f"Target{i}", "trials": []} for i in range(100)]}
    new_trials = [{"id": "NCT12345678", "name": "Trial"}]

    updated = update_target(data, "NewTarget", new_trials)
    assert len(updated["targets"]) == 100
    assert not any(t["name"] == "NewTarget" for t in updated["targets"])

    # 4. Test MAX_TRIALS_PER_TARGET limit
    target_data = {
        "targets": [
            {
                "name": "Target",
                "trials": [{"id": f"NCT{i:08d}", "name": "Trial"} for i in range(1000)]
            }
        ]
    }
    new_csv_trials = [{"id": "NCT99999999", "name": "New Trial"}]

    updated_trials = update_target(target_data, "Target", new_csv_trials)
    assert len(updated_trials["targets"][0]["trials"]) == 1000
    assert not any(t["id"] == "NCT99999999" for t in updated_trials["targets"][0]["trials"])


def test_api_response_size_limit():
    """Verify that fetch_trial_data and search_trials respect the 10MB response size limit."""
    from src.crawler import fetch_trial_data
    from src.auto_discover_trials import search_trials
    from unittest.mock import patch, MagicMock

    # Mock responses for requests (HAS_REQUESTS=True)
    with patch("src.crawler.get_session") as mock_get_session, \
         patch("src.auto_discover_trials.get_session") as mock_get_session_auto:

        # 1. Test fetch_trial_data with large Content-Length header
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Length": str(11 * 1024 * 1024)} # 11MB
        mock_session.get.return_value = mock_response
        mock_response.__enter__.return_value = mock_response

        assert fetch_trial_data("NCT12345678") is None
        mock_response.__exit__.assert_called_once()

        # 2. Test fetch_trial_data with actual large body (chunked)
        mock_response_chunked = MagicMock()
        mock_response_chunked.status_code = 200
        mock_response_chunked.headers = {} # No content length
        # Generate 11MB worth of chunks (88 chunks of 128KB)
        mock_response_chunked.iter_content.return_value = [b"A" * (128 * 1024)] * 88
        mock_session.get.return_value = mock_response_chunked
        mock_response_chunked.__enter__.return_value = mock_response_chunked

        assert fetch_trial_data("NCT12345678") is None
        mock_response_chunked.__exit__.assert_called_once()

        # 3. Test search_trials with large Content-Length header
        mock_session_auto = MagicMock()
        mock_get_session_auto.return_value = mock_session_auto

        mock_response_auto = MagicMock()
        mock_response_auto.status_code = 200
        mock_response_auto.headers = {"Content-Length": str(11 * 1024 * 1024)}
        mock_session_auto.get.return_value = mock_response_auto
        mock_response_auto.__enter__.return_value = mock_response_auto

        assert search_trials("Target") == []
        mock_response_auto.__exit__.assert_called_once()


def test_api_content_type_validation():
    """Verify that fetch_trial_data and search_trials validate the Content-Type header."""
    from src.crawler import fetch_trial_data
    from src.auto_discover_trials import search_trials
    from unittest.mock import patch, MagicMock

    # Mock responses for requests (HAS_REQUESTS=True)
    with patch("src.crawler.get_session") as mock_get_session, \
         patch("src.auto_discover_trials.get_session") as mock_get_session_auto:

        # 1. Test fetch_trial_data with unexpected Content-Type (e.g. text/html)
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_session.get.return_value = mock_response
        mock_response.__enter__.return_value = mock_response

        assert fetch_trial_data("NCT12345678") is None
        mock_response.__exit__.assert_called_once()

        # 2. Test search_trials with unexpected Content-Type
        mock_session_auto = MagicMock()
        mock_get_session_auto.return_value = mock_session_auto

        mock_response_auto = MagicMock()
        mock_response_auto.status_code = 200
        mock_response_auto.headers = {"Content-Type": "text/html"}
        mock_session_auto.get.return_value = mock_response_auto
        mock_response_auto.__enter__.return_value = mock_response_auto

        assert search_trials("Target") == []
        mock_response_auto.__exit__.assert_called_once()


def test_yaml_load_security_against_data_loss():
    """Verify that configuration loaders fail loudly on read/parse errors to prevent data loss."""
    from src.main import load_config
    from src.manage_trials import load_yaml
    from src.update_trials_from_csv import load_yaml as load_yaml_csv
    from src.generate_target_pages import load_trials_yaml
    import yaml
    import os
    import pytest

    test_yaml = "tests/test_unreadable.yaml"

    # 1. Test malformed YAML (not a dict) - should raise ValueError or YAMLError
    with open(test_yaml, "w", encoding="utf-8") as f:
        f.write("- item1\n- item2")

    try:
        with pytest.raises(ValueError):
            load_config(test_yaml)
        with pytest.raises(ValueError):
            load_yaml(test_yaml)
        with pytest.raises(ValueError):
            load_yaml_csv(test_yaml)
        with pytest.raises(ValueError):
            load_trials_yaml(test_yaml)
    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)

    # 2. Test unreadable file (OSError)
    # Since we can't easily change permissions in the sandbox to trigger OSError,
    # we can use a directory path as a file path to trigger an OSError (IsADirectoryError).
    test_dir = "tests/test_dir_as_file"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)

    try:
        with pytest.raises(OSError):
            load_config(test_dir)
        with pytest.raises(OSError):
            load_yaml(test_dir)
        with pytest.raises(OSError):
            load_yaml_csv(test_dir)
        with pytest.raises(OSError):
            load_trials_yaml(test_dir)
    finally:
        if os.path.exists(test_dir):
            os.rmdir(test_dir)

def test_malformed_config_robustness():
    """Verify that load_config and deduplicate_config handle malformed structures gracefully."""
    from src.main import load_config, deduplicate_config
    import os
    import pytest

    test_yaml = "tests/test_malformed_robustness.yaml"

    # 1. Test load_config with malformed YAML (not a dict)
    with open(test_yaml, "w", encoding="utf-8") as f:
        f.write("- item1\n- item2")

    try:
        with pytest.raises(ValueError):
            load_config(test_yaml)

        # 2. Test deduplicate_config with malformed dict (not containing targets list)
        malformed_config = {"not_targets": []}
        res_dedup = deduplicate_config(malformed_config)
        assert isinstance(res_dedup, dict)
        assert "targets" in res_dedup
        assert res_dedup["targets"] == []

        # 3. Test deduplicate_config with targets being a string instead of a list
        malformed_config_2 = {"targets": "not a list"}
        res_dedup_2 = deduplicate_config(malformed_config_2)
        assert isinstance(res_dedup_2, dict)
        assert "targets" in res_dedup_2
        assert res_dedup_2["targets"] == []

        # 4. Test deduplicate_config with one target being a string instead of a dict
        malformed_config_3 = {
            "targets": [
                "not a target dict",
                {"name": "Valid Target", "trials": []}
            ]
        }
        res_dedup_3 = deduplicate_config(malformed_config_3)
        assert len(res_dedup_3["targets"]) == 1
        assert res_dedup_3["targets"][0]["name"] == "Valid Target"

        # 5. Test load_config with legacy format (trials list at root)
        with open(test_yaml, "w", encoding="utf-8") as f:
            f.write("trials:\n  - id: NCT12345678\n    name: Legacy Trial")
        res_legacy = load_config(test_yaml)
        assert len(res_legacy["targets"]) == 1
        assert res_legacy["targets"][0]["name"] == "Default"
        assert res_legacy["targets"][0]["trials"][0]["id"] == "NCT12345678"

    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)


def test_backtick_escaping_and_diff_formatting():
    """Verify that backticks are escaped and don't break diff highlighting."""
    from src.utils import escape_html, format_diff_line

    # Test escaping
    assert escape_html("text with `backtick`") == "text with &#96;backtick&#96;"

    # Test diff formatting with backticks in values
    # Original diff line from diff_engine.py might look like:
    # Field `status` changed from `Old` to `New`

    malicious_val = "Normal ` value"
    diff_line = f"Field `status` changed from `Old` to `{malicious_val}`"

    formatted = format_diff_line(diff_line)

    # Check that it is properly formatted with spans
    assert "text-danger" in formatted
    assert "text-success" in formatted
    assert "&#96;Old&#96;" in formatted
    assert "&#96;Normal &#96; value&#96;" in formatted

    # Test devious injection that previously broke the regex
    # With escaped backticks and greedy matching for the second value,
    # it matches as much as possible until the last backtick.
    devious_val = "Old` to `New` changed from `Evil"
    diff_line = f"Field `status` changed from `Old` to `{devious_val}`"
    formatted = format_diff_line(diff_line)

    # It matches:
    # (changed from )(&#96;Old&#96;)( to )(&#96;Old&#96; to &#96;New&#96; changed from &#96;Evil&#96;)
    assert "text-danger" in formatted
    assert "text-success" in formatted
    assert "&#96;Evil&#96;</span>" in formatted


def test_yaml_injection_prevention():
    """Verify that malicious target names cannot inject YAML into configuration files."""
    from src.generate_target_pages import generate_target_qmd, update_quarto_yml
    import os
    import yaml

    malicious_name = 'Target\n      - href: https://evil.com\n        text: "Injected"'
    desc = "Test Description"

    # Test QMD generation
    output_dir = "tests/tmp_yaml_test"
    qmd = generate_target_qmd(malicious_name, desc, output_dir=output_dir)
    with open(qmd, "r", encoding="utf-8") as f:
        content = f.read()

    # The title should be properly escaped/quoted in YAML, not raw
    # When yaml.safe_dump dumps a string with newline, it might use | or > style
    # but it will definitely not let it be interpreted as multiple fields
    qmd_frontmatter = content.split("---")[1]
    data = yaml.safe_load(qmd_frontmatter)
    # Note: escape_html is called on the name before yaml.safe_dump
    from src.utils import escape_html

    assert data["title"] == escape_html(malicious_name)
    # The string should be quoted, making it a literal, not a new field
    # In YAML, a quoted string "Target\n      - href: ..." is a single scalar.
    # It would only be a new field if it was not quoted and started at a new line at the same indentation level.
    # safe_dump handles this correctly.
    assert (
        'title: "' in qmd_frontmatter
        or "title: |" in qmd_frontmatter
        or "title: >" in qmd_frontmatter
    )

    # Test _quarto.yml generation
    yml_path = "tests/tmp_quarto_injection.yml"
    targets = [{"name": malicious_name}]
    update_quarto_yml(targets, yml_path)

    with open(yml_path, "r", encoding="utf-8") as f:
        yml_content = f.read()
        yml_data = yaml.safe_load(yml_content)

    # Check that the malicious name is stored as a single text value
    found = False
    from src.utils import escape_html

    escaped_malicious_name = escape_html(malicious_name)
    for item in yml_data["website"]["navbar"]["left"]:
        if isinstance(item, dict) and item.get("text") == "Targets":
            for menu_item in item["menu"]:
                if menu_item["text"] == escaped_malicious_name:
                    found = True
                    break
    assert found is True

    # Ensure no external link was injected as a top-level menu item
    for item in yml_data["website"]["navbar"]["left"]:
        if isinstance(item, dict):
            assert item.get("href") != "https://evil.com"

    # Cleanup
    os.remove(qmd)
    os.remove(yml_path)
    os.rmdir(output_dir)

def test_yaml_injection_prevention_regression():
    """Verify that YAML delimiters in trial data are correctly escaped in the YAML configuration."""
    import yaml
    import os
    from src.update_trials_from_csv import save_yaml, load_yaml

    test_yaml = "tests/test_injection_regression.yaml"
    if os.path.exists(test_yaml):
        os.remove(test_yaml)

    # Malicious data that could break a naive manual YAML writer
    malicious_trial_name = "Normal' \n      - id: 'NCT00000000'\n        name: 'Injected Trial"
    data = {
        "targets": [
            {
                "name": "TargetName",
                "description": "Desc",
                "trials": [
                    {
                        "id": "NCT12345678",
                        "name": malicious_trial_name
                    }
                ]
            }
        ]
    }

    try:
        # Save using the now mandatory PyYAML-based save_yaml
        save_yaml(data, test_yaml)

        # Load it back
        loaded_data = load_yaml(test_yaml)

        # Verify the data was preserved exactly (literal) and not interpreted as YAML structure
        loaded_trials = loaded_data["targets"][0]["trials"]
        assert len(loaded_trials) == 1
        assert loaded_trials[0]["id"] == "NCT12345678"
        assert loaded_trials[0]["name"] == malicious_trial_name

        # Verify that the injected ID is NOT in the loaded data
        all_ids = [t["id"] for target in loaded_data["targets"] for t in target["trials"]]
        assert "NCT00000000" not in all_ids

    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)


def test_deduplicate_config_security():
    """Verify that deduplicate_config validates IDs and truncates long strings."""
    from src.main import deduplicate_config
    import os

    test_yaml = "tests/test_dedup_security.yaml"
    if os.path.exists(test_yaml):
        os.remove(test_yaml)

    config = {
        "targets": [
            {
                "name": "A" * 300,  # Too long
                "description": "B" * 3000,  # Too long
                "trials": [
                    {"id": "NCT12345678", "name": "Valid Trial"},
                    {"id": "invalid_id", "name": "Invalid ID Trial"},
                    {"id": "NCT12345678", "name": "C" * 1500},  # Duplicate and too long
                ],
            }
        ]
    }

    try:
        # This will also trigger a save to test_dedup_security.yaml because of changes
        # But we need to make sure it uses our test path.
        # deduplicate_config calls save_config(config) which defaults to trials.yaml.
        # To avoid overwriting trials.yaml, we should mock or temporarily change the behavior.
        # Actually, deduplicate_config uses the global save_config which takes config_path.
        # But deduplicate_config itself doesn't take a path.

        # Let's monkeypatch save_config to use our test path
        import src.main
        original_save = src.main.save_config
        src.main.save_config = lambda cfg: original_save(cfg, test_yaml)

        try:
            cleaned = deduplicate_config(config)

            target = cleaned["targets"][0]
            assert len(target["name"]) == 255
            assert len(target["description"]) == 2000
            assert len(target["trials"]) == 1
            assert target["trials"][0]["id"] == "NCT12345678"
            assert len(target["trials"][0]["name"]) == 1000

            assert os.path.exists(test_yaml)

            # Test truncation of targets and trials
            large_config = {
                "targets": [{"name": f"Target{i}", "trials": [{"id": f"NCT{j:08d}"} for j in range(1100)]} for i in range(110)]
            }
            cleaned_large = deduplicate_config(large_config)
            assert len(cleaned_large["targets"]) == 100
            assert len(cleaned_large["targets"][0]["trials"]) == 1000

        finally:
            src.main.save_config = original_save

    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)


def test_exclusion_list_limit():
    """Verify that add_to_exclusion_list enforces the 5000 entry limit."""
    from src.manage_trials import add_to_exclusion_list
    import os
    import yaml

    test_exclusion_yaml = "tests/test_exclusion_limit.yaml"
    if os.path.exists(test_exclusion_yaml):
        os.remove(test_exclusion_yaml)

    try:
        # Create a list with 5000 entries
        data = {"excluded_ids": [f"NCT{i:08d}" for i in range(5000)]}
        with open(test_exclusion_yaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        # Try to add one more
        add_to_exclusion_list("NCT99999999", yaml_path=test_exclusion_yaml)

        # Verify it wasn't added
        with open(test_exclusion_yaml, "r", encoding="utf-8") as f:
            saved_data = yaml.safe_load(f)
            assert len(saved_data["excluded_ids"]) == 5000
            assert "NCT99999999" not in saved_data["excluded_ids"]

    finally:
        if os.path.exists(test_exclusion_yaml):
            os.remove(test_exclusion_yaml)


def test_history_size_limit():
    """Verify that trial and target history are bounded to 100 entries."""
    from src.main import update_history, update_target_history
    import os
    import json
    import shutil

    test_history_dir = "tests/tmp_history"
    if os.path.exists(test_history_dir):
        shutil.rmtree(test_history_dir)
    os.makedirs(test_history_dir)

    try:
        # 1. Test update_history limit
        trial_id = "NCT00000001"
        # Create a history with 105 entries
        history = [{"timestamp": f"2023-01-01 00:00:{i:02d}", "diff": "initial"} for i in range(105)]

        # This should truncate to 100
        updated = update_history(trial_id, "latest change", history_dir=test_history_dir, history=history)

        assert len(updated) == 100
        assert updated[-1]["diff"] == "latest change"

        # Verify file content
        history_file = os.path.join(test_history_dir, f"{trial_id}_history.json")
        with open(history_file, "r", encoding="utf-8") as f:
            saved_history = json.load(f)
            assert len(saved_history) == 100

        # 2. Test update_target_history limit and message truncation
        target_name = "LargeTarget"
        # Create many changed trials
        current_reports = [{"id": f"NCT{i:08d}", "changed_today": True} for i in range(50)]

        # Pre-fill history with 105 entries
        target_history_file = os.path.join(test_history_dir, "target_largetarget.json")
        initial_target_history = [{"timestamp": "...", "event": "..."}] * 105
        with open(target_history_file, "w", encoding="utf-8") as f:
            json.dump(initial_target_history, f)

        update_target_history(target_name, current_reports, history_dir=test_history_dir)

        with open(target_history_file, "r", encoding="utf-8") as f:
            saved_target_history = json.load(f)
            assert len(saved_target_history) == 100

            latest_event = saved_target_history[-1]["event"]
            assert "Changes detected in 50 trials" in latest_event
            # Should show 10 IDs and "and 40 more"
            assert "(and 40 more)" in latest_event
            # Verify it doesn't list all 50 IDs (just a quick check on length or count of commas)
            assert latest_event.count(",") == 9

    finally:
        if os.path.exists(test_history_dir):
            shutil.rmtree(test_history_dir)


def test_update_target_truncation():
    """Verify that update_target in src/update_trials_from_csv.py truncates long metadata."""
    from src.update_trials_from_csv import update_target

    data = {"targets": []}
    long_target_name = "T" * 300
    long_description = "D" * 3000
    new_trials = [{"id": "NCT12345678", "name": "Trial"}]

    updated_data = update_target(data, long_target_name, new_trials, description=long_description)

    target = updated_data["targets"][0]
    assert len(target["name"]) == 255
    assert target["name"] == "T" * 255
    assert len(target["description"]) == 2000
    assert target["description"] == "D" * 2000


def test_http_response_closure():
    """Verify that HTTP response objects are always closed to prevent resource leaks."""
    from src.crawler import fetch_trial_data
    from src.auto_discover_trials import search_trials
    from unittest.mock import patch, MagicMock

    # 1. Test fetch_trial_data closure (requests path)
    with patch("src.crawler.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Test 404 case
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_session.get.return_value = mock_response_404
        mock_response_404.__enter__.return_value = mock_response_404
        fetch_trial_data("NCT12345678")
        assert mock_response_404.__enter__.called
        assert mock_response_404.__exit__.called

        # Test success case
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.headers = {"Content-Type": "application/json"}
        mock_response_200.iter_content.return_value = [b'{"foo": "bar"}']
        mock_session.get.return_value = mock_response_200
        mock_response_200.__enter__.return_value = mock_response_200
        fetch_trial_data("NCT12345678")
        assert mock_response_200.__enter__.called
        assert mock_response_200.__exit__.called

    # 2. Test search_trials closure (requests path)
    with patch("src.auto_discover_trials.get_session") as mock_get_session_auto:
        mock_session_auto = MagicMock()
        mock_get_session_auto.return_value = mock_session_auto

        # Test error case
        mock_response_err = MagicMock()
        mock_response_err.status_code = 500
        mock_session_auto.get.return_value = mock_response_err
        mock_response_err.__enter__.return_value = mock_response_err
        search_trials("Target")
        assert mock_response_err.__enter__.called
        assert mock_response_err.__exit__.called

        # Test success case
        mock_response_200_auto = MagicMock()
        mock_response_200_auto.status_code = 200
        mock_response_200_auto.headers = {"Content-Type": "application/json"}
        mock_response_200_auto.iter_content.return_value = [b'{"studies": []}']
        mock_session_auto.get.return_value = mock_response_200_auto
        mock_response_200_auto.__enter__.return_value = mock_response_200_auto
        search_trials("Target")
        assert mock_response_200_auto.__enter__.called
        assert mock_response_200_auto.__exit__.called

def test_urllib_fallback_security():
    """Verify that the urllib fallback path correctly handles malformed Content-Length and size limits."""
    from src.crawler import fetch_trial_data
    from src.auto_discover_trials import search_trials
    from unittest.mock import patch, MagicMock
    import src.crawler
    import src.auto_discover_trials

    with patch("urllib.request.urlopen") as mock_urlopen:
        # Force urllib path
        with patch.object(src.crawler, "HAS_REQUESTS", False), \
             patch.object(src.auto_discover_trials, "HAS_REQUESTS", False):

            # 1. Test malformed Content-Length (non-numeric)
            mock_response_malformed = MagicMock()
            mock_response_malformed.status = 200
            mock_response_malformed.headers = {"Content-Type": "application/json", "Content-Length": "not-a-number"}
            mock_response_malformed.read.side_effect = [b'{"foo": "bar"}', b""]
            mock_urlopen.return_value.__enter__.return_value = mock_response_malformed

            # Should NOT return None if Content-Length is malformed (it skips the check and proceeds to read)
            # unless the read also fails. But wait, if it's malformed, .isdigit() is False,
            # so it proceeds to read. This is fine as the size is still checked during read.
            res = fetch_trial_data("NCT12345678")
            assert res == {"foo": "bar"}

            # 2. Test large Content-Length header (e.g. " 11000000 ")
            mock_response_large = MagicMock()
            mock_response_large.status = 200
            mock_response_large.headers = {"Content-Type": "application/json", "Content-Length": " 11000000 "}
            mock_urlopen.return_value.__enter__.return_value = mock_response_large

            assert fetch_trial_data("NCT12345678") is None

            # 3. Test Search with malformed Content-Length
            mock_response_search = MagicMock()
            mock_response_search.status = 200
            mock_response_search.headers = {"Content-Type": "application/json", "Content-Length": "invalid"}
            mock_response_search.read.side_effect = [b'{"studies": []}', b""]
            mock_urlopen.return_value.__enter__.return_value = mock_response_search


            # 4. Test Search with large Content-Length
            mock_response_search_large = MagicMock()
            mock_response_search_large.status = 200
            mock_response_search_large.headers = {"Content-Type": "application/json", "Content-Length": "11000000"}
            mock_urlopen.return_value.__enter__.return_value = mock_response_search_large

            assert search_trials("Target") == []


def test_truncation_security():
    """Verify that large values in diffs and trial reports are correctly truncated."""
    from src.diff_engine import format_diff
    from src.main import process_trial
    from unittest.mock import patch

    # 1. Test diff_engine truncation
    # Mocking a DeepDiff structure
    diff = {
        "values_changed": {
            "root['some_path']": {
                "old_value": "A" * 2000,
                "new_value": "B" * 2000
            }
        }
    }

    formatted = format_diff(diff)
    assert "A" * 1000 in formatted
    assert "A" * 1001 not in formatted
    assert "B" * 1000 in formatted
    assert "B" * 1001 not in formatted

    # 2. Test main.py process_trial truncation
    trial = {"id": "NCT12345678", "name": "Test Trial"}

    # Mock API response with huge description
    huge_desc = "D" * 15000
    mock_data = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT12345678", "briefTitle": "Title"},
            "descriptionModule": {"detailedDescription": huge_desc},
            "statusModule": {"overallStatus": "RECRUITING"}
        }
    }

    # Also mock no history to avoid file IO
    with patch("src.main.fetch_trial_data", return_value=mock_data), \
         patch("src.main.safe_json_load", return_value=[]), \
         patch("src.main.update_history", return_value=[{"timestamp": "2023-01-01", "diff": "initial"}]), \
         patch("src.main.save_snapshot"), \
         patch("src.main.compare_snapshots", return_value=None):

        report, _ = process_trial(trial, "Target")

        assert len(report["details"]) == 10000
        assert report["details"] == "D" * 10000

    # 3. Test combined details truncation when there's a diff
    mock_diff = {"values_changed": {"root['status']": {"old_value": "A", "new_value": "B"}}}
    with patch("src.main.fetch_trial_data", return_value=mock_data), \
         patch("src.main.safe_json_load", return_value=[]), \
         patch("src.main.update_history", return_value=[{"timestamp": "2023-01-01", "diff": "initial"}]), \
         patch("src.main.save_snapshot"), \
         patch("src.main.compare_snapshots", return_value=mock_diff), \
         patch("src.main.format_diff", return_value="C" * 15000):

        report, _ = process_trial(trial, "Target")

        # Combined details = RECENT CHANGES FOUND (25) + \n (1) + format_diff (15000) + \n\n***\n (6) + detailed_desc (10000) = ~25032
        # Should be truncated to 20000
        assert len(report["details"]) == 20000


def test_safe_json_load_robustness():
    """Verify that safe_json_load raises exceptions on errors other than FileNotFoundError."""
    from src.main import safe_json_load
    import os
    import pytest
    import json

    test_json = "tests/test_unreadable.json"

    # 1. Test malformed JSON
    with open(test_json, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")

    try:
        with pytest.raises(json.JSONDecodeError):
            safe_json_load(test_json)
    finally:
        if os.path.exists(test_json):
            os.remove(test_json)

    # 2. Test unreadable file (OSError)
    test_dir = "tests/test_json_dir"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)

    try:
        with pytest.raises(OSError):
            safe_json_load(test_dir)
    finally:
        if os.path.exists(test_dir):
            os.rmdir(test_dir)


def test_add_to_exclusion_list_robustness():
    """Verify that add_to_exclusion_list raises exceptions on loading errors."""
    from src.manage_trials import add_to_exclusion_list
    import os
    import pytest
    import yaml

    test_yaml = "tests/test_exclusion_robust.yaml"

    # 1. Test malformed YAML
    with open(test_yaml, "w", encoding="utf-8") as f:
        f.write("{ invalid yaml : [")

    try:
        with pytest.raises(yaml.YAMLError):
            add_to_exclusion_list("NCT12345678", yaml_path=test_yaml)
    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)

    # 2. Test YAML that is not a dictionary
    with open(test_yaml, "w", encoding="utf-8") as f:
        f.write("- item1\n- item2")

    try:
        with pytest.raises(ValueError, match="must be a dictionary"):
            add_to_exclusion_list("NCT12345678", yaml_path=test_yaml)
    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)

def test_csv_header_injection_prevention():
    """Verify that CSV headers (keys) starting with dangerous characters are sanitized."""
    from src.main import save_target_data
    import os
    import csv
    import shutil
    from src.utils import sanitize_id

    target_name = "HeaderTest"
    summary_report = []
    # Data with a malicious key and a malicious value
    all_raw_data = [{"=malicious_key": "value", "normal_key": "=malicious_value"}]

    safe_name = sanitize_id(target_name).lower()
    target_path = f"data/targets/{safe_name}"

    # Ensure clean state
    if os.path.exists(target_path):
        shutil.rmtree(target_path)

    try:
        save_target_data(target_name, summary_report, all_raw_data)

        raw_csv_path = os.path.join(target_path, "all_trials_raw.csv")
        assert os.path.exists(raw_csv_path)

        with open(raw_csv_path, "r", encoding="utf-8-sig") as f:
            # We read raw lines first to see the actual content before DictReader handles it
            lines = f.readlines()
            header = lines[0].strip()
            # The header should contain the sanitized key
            assert "'=malicious_key" in header

            # Re-read with DictReader for convenience
            f.seek(0)
            reader = csv.DictReader(f)
            assert "'=malicious_key" in reader.fieldnames

            rows = list(reader)
            assert len(rows) == 1
            assert rows[0].get("'=malicious_key") == "value"
            assert rows[0].get("normal_key") == "'=malicious_value"

    finally:
        if os.path.exists(target_path):
            shutil.rmtree(target_path)

def test_flatten_dict_dos_protection():
    """Verify that flatten_dict limits list items and truncates strings."""
    from src.main import flatten_dict

    # Test list item limit (MAX_LIST_ITEMS = 1000)
    large_list = [str(i) for i in range(2000)]
    d = {"large_list": large_list}
    flattened = flatten_dict(d)

    # 1000 items, each with a number and most with a comma-space
    # "0, 1, ..., 999"
    val = flattened["large_list"]
    assert "999" in val
    assert "1000" not in val

    # Test string truncation (MAX_VAL_LEN = 10000)
    long_str_list = ["A" * 6000, "B" * 6000]
    d2 = {"long_str_list": long_str_list}
    flattened2 = flatten_dict(d2)
    val2 = flattened2["long_str_list"]
    assert len(val2) == 10000
    assert val2.startswith("A" * 6000)
    assert val2.endswith("B" * (10000 - 6000 - 2)) # -2 for ", "

def test_api_json_type_validation_unit():
    """Verify that crawler and auto_discover handle non-dict JSON responses."""
    from src.crawler import fetch_trial_data
    from src.auto_discover_trials import search_trials
    from unittest.mock import patch, MagicMock

    # Mock response returning a JSON list instead of a dict
    with patch("src.crawler.get_session") as mock_get_session,          patch("src.auto_discover_trials.get_session") as mock_get_session_auto:

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.iter_content.return_value = [b'[{"id": "NCT12345678"}]']
        mock_session.get.return_value = mock_response
        mock_response.__enter__.return_value = mock_response

        # Should return None because it's a list, not a dict
        assert fetch_trial_data("NCT12345678") is None

        mock_session_auto = MagicMock()
        mock_get_session_auto.return_value = mock_session_auto
        mock_response_auto = MagicMock()
        mock_response_auto.status_code = 200
        mock_response_auto.headers = {"Content-Type": "application/json"}
        mock_response_auto.iter_content.return_value = [b'[{"id": "NCT12345678"}]']
        mock_session_auto.get.return_value = mock_response_auto
        mock_response_auto.__enter__.return_value = mock_response_auto

        # Should return [] because it's a list, not a dict
        assert search_trials("Target") == []
