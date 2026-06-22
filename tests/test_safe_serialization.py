import pytest
import json
from src.utils import safe_str, safe_json_dumps, MAX_VALUE_LENGTH

def test_safe_str_recursion():
    """Verify that safe_str handles RecursionError gracefully."""
    class RecursiveObj:
        def __str__(self):
            return str(self)

    obj = RecursiveObj()
    # In a real environment, this would raise RecursionError if not handled
    # We can't easily trigger a real RecursionError without deep nesting or mocking
    # but we can mock the __str__ to raise it.

    with pytest.raises(RecursionError):
        str(obj)

    assert safe_str(obj) == "[Complex Object: Too Deep]"

def test_safe_str_truncation():
    """Verify that safe_str enforces the length limit."""
    long_str = "A" * (MAX_VALUE_LENGTH + 100)
    res = safe_str(long_str)
    assert len(res) == MAX_VALUE_LENGTH
    assert res == "A" * MAX_VALUE_LENGTH

def test_safe_json_dumps_recursion():
    """Verify that safe_json_dumps handles RecursionError gracefully."""
    # Create a circular reference (json.dumps handles this with ValueError usually,
    # but some custom objects or very deep nesting might raise RecursionError)

    # Let's mock json.dumps to raise RecursionError
    import json as real_json
    from unittest.mock import patch

    with patch("json.dumps", side_effect=RecursionError):
        assert safe_json_dumps({"a": 1}) == '"[Complex Object: Too Deep]"'

def test_safe_json_dumps_truncation():
    """Verify that safe_json_dumps enforces the length limit."""
    data = {"key": "A" * MAX_VALUE_LENGTH}
    res = safe_json_dumps(data)
    # The JSON string will be slightly longer than MAX_VALUE_LENGTH due to quotes and braces
    # but the result should be truncated exactly at MAX_VALUE_LENGTH.
    assert len(res) == MAX_VALUE_LENGTH

def test_safe_str_types():
    """Verify that safe_str handles various types correctly."""
    assert safe_str(123) == "123"
    assert safe_str(None) == "None"
    assert safe_str([1, 2, 3], max_length=5) == "[1, 2"
