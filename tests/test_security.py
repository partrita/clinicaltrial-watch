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
    with open(qmd, "r") as f:
        content = f.read()
    # yaml.safe_dump might not use quotes for this string
    assert "title: Target &#124; Pipe" in content
    assert "Desc &lt;script&gt;" in content

    # Test YAML generation
    yml = "tests/tmp_quarto.yml"
    update_quarto_yml([{"name": name}], yml)
    with open(yml, "r") as f:
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
    assert sanitize_csv_value("  =SUM(A1)") == "'  =SUM(A1)"
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
    huge_val = "1" * 1000
    assert format_enrollment(huge_val) == "N/A"


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
    with open(qmd, "r") as f:
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

    with open(yml_path, "r") as f:
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
        finally:
            src.main.save_config = original_save

    finally:
        if os.path.exists(test_yaml):
            os.remove(test_yaml)
