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
    assert 'title: "Target &#124; Pipe"' in content
    assert "Desc &lt;script&gt;" in content

    # Test YAML generation
    yml = "tests/tmp_quarto.yml"
    update_quarto_yml([{"name": name}], yml)
    with open(yml, "r") as f:
        content = f.read()
    assert 'text: "Target &#124; Pipe"' in content

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
