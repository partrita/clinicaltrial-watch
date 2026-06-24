from src.main import flatten_dict
from unittest.mock import patch


def test_flatten_recursion_hardening():
    """Verify that flatten_dict handles deeply nested structures in lists without crashing."""

    # 1. Test json.dumps recursion hardening
    deep_dict = {"a": "b"}
    # The first item determines the processing path.
    # We want to enter the "else" branch (complex types)
    data = {"my_list": [deep_dict]}

    with patch("json.dumps", side_effect=RecursionError):
        print("Testing with mocked RecursionError in json.dumps...")
        result = flatten_dict(data)
        assert "my_list" in result
        assert '"[Complex Object: Too Deep]"' in result["my_list"]
        print("Success: Placeholder found in result (mocked json.dumps).")

    # 2. Test str() recursion hardening
    # The first item determines the processing path.
    # If first item is int, it enters the scalar path.
    # We can use a custom object for a subsequent item.
    class RecursiveStr:
        def __str__(self):
            raise RecursionError("Mocked recursion")

    data2 = {"my_list": [123, RecursiveStr()]}
    print("Testing with object that raises RecursionError in str()...")
    result2 = flatten_dict(data2)
    assert "my_list" in result2
    assert "[Complex Object: Too Deep]" in result2["my_list"]
    print("Success: Placeholder found in result (recursive str).")


if __name__ == "__main__":
    test_flatten_recursion_hardening()
    print("Verification script passed successfully!")
