import pytest
from src.main import flatten_dict, MAX_DEPTH

def test_flatten_dict_depth_limit():
    """Verify that flatten_dict respects the MAX_DEPTH limit to prevent DoS."""
    # Create a deeply nested dictionary
    # level 0: { "l0": { ... } }
    # level 1: { "l0_l1": { ... } }
    # ...
    deep_dict = {"leaf_deep": "I am too deep"}
    for i in range(MAX_DEPTH + 10):
        deep_dict = {f"l{MAX_DEPTH + 10 - i}": deep_dict}

    # Add a shallow leaf
    deep_dict["leaf_shallow"] = "I am shallow"

    # Flattening should not crash
    flattened = flatten_dict(deep_dict)

    # Shallow leaf should be present
    assert flattened["leaf_shallow"] == "I am shallow"

    # Deep leaf should NOT be present
    # The key would be very long with many underscores
    for key in flattened.keys():
        assert key.count("_") < MAX_DEPTH
        assert "leaf_deep" not in key

def test_flatten_dict_normal_nesting():
    """Verify that flatten_dict works correctly for normal nesting."""
    d = {
        "user": {
            "id": 1,
            "info": {
                "name": "Sentinel",
                "role": "Security"
            }
        },
        "tags": ["security", "audit"]
    }

    flattened = flatten_dict(d)
    assert flattened["user_id"] == 1
    assert flattened["user_info_name"] == "Sentinel"
    assert flattened["user_info_role"] == "Security"
    assert flattened["tags"] == "security, audit"
