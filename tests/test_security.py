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
    assert sanitize_id("Breast Cancer (Triple Negative)") == "Breast_Cancer__Triple_Negative"
    assert sanitize_id("") == "unknown"
    assert sanitize_id(None) == "unknown"

def test_sanitize_id_length_limit():
    long_id = "A" * 300
    sanitized = sanitize_id(long_id)
    assert len(sanitized) <= 255
    assert sanitized == "A" * 255

def test_escape_html_basic():
    # html.escape escapes ' as &#x27;
    assert escape_html("<script>alert('xss')</script>") == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
    assert escape_html('Hello "World" & others') == "Hello &quot;World&quot; &amp; others"

def test_escape_html_markdown():
    # Pipe character should be escaped to prevent Markdown table injection
    assert escape_html("Data | with | pipes") == "Data &#124; with &#124; pipes"
    # Brackets should be escaped to prevent Markdown link injection
    assert escape_html("Link [text](url)") == "Link &#91;text&#93;(url)"

def test_escape_html_none():
    assert escape_html(None) == ""

def test_is_valid_nct_id():
    assert is_valid_nct_id("NCT12345678") is True
    assert is_valid_nct_id("NCT00000000") is True
    assert is_valid_nct_id("NCT1234567") is False # Too short
    assert is_valid_nct_id("NCT123456789") is False # Too long
    assert is_valid_nct_id("nct12345678") is False # Case sensitive
    assert is_valid_nct_id("NCTabcdefgh") is False # Not digits
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
                    "briefTitle": "Valid Trial"
                }
            }
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "evil",
                    "briefTitle": "Invalid Trial"
                }
            }
        }
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
    assert fetch_trial_data("NCT1234") is None # Too short

def test_sanitize_csv_value():
    """Verify that CSV formula injection is prevented."""
    from src.utils import sanitize_csv_value

    assert sanitize_csv_value("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert sanitize_csv_value("+42") == "'+42"
    assert sanitize_csv_value("-5") == "'-5"
    assert sanitize_csv_value("@something") == "'@something"
    assert sanitize_csv_value("Normal text") == "Normal text"
    assert sanitize_csv_value(123) == 123
    assert sanitize_csv_value(None) is None
    assert sanitize_csv_value("") == ""

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
    qmd_frontmatter = content.split('---')[1]
    data = yaml.safe_load(qmd_frontmatter)
    # Note: escape_html is called on the name before yaml.safe_dump
    from src.utils import escape_html
    assert data['title'] == escape_html(malicious_name)
    # The string should be quoted, making it a literal, not a new field
    # In YAML, a quoted string "Target\n      - href: ..." is a single scalar.
    # It would only be a new field if it was not quoted and started at a new line at the same indentation level.
    # safe_dump handles this correctly.
    assert 'title: "' in qmd_frontmatter or 'title: |' in qmd_frontmatter or 'title: >' in qmd_frontmatter

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
    for item in yml_data['website']['navbar']['left']:
        if isinstance(item, dict) and item.get('text') == 'Targets':
            for menu_item in item['menu']:
                if menu_item['text'] == escaped_malicious_name:
                    found = True
                    break
    assert found is True

    # Ensure no external link was injected as a top-level menu item
    for item in yml_data['website']['navbar']['left']:
        if isinstance(item, dict):
            assert item.get('href') != "https://evil.com"

    # Cleanup
    os.remove(qmd)
    os.remove(yml_path)
    os.rmdir(output_dir)
