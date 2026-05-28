import pytest
from src.main import flatten_dict, MAX_DEPTH

def test_flatten_dict_depth_limit():
    """Verify that flatten_dict stops at MAX_DEPTH to prevent recursion DoS."""
    # Create a deeply nested dictionary
    # depth 0: {'level0': {...}}
    # depth 1: {'level0': {'level1': {...}}}
    # ...
    # depth 20: {'level0': ... {'level20': 'leaf'} ...}

    depth = 25
    nested = "leaf"
    for i in range(depth, -1, -1):
        nested = {f"level{i}": nested}

    flattened = flatten_dict(nested)

    # After 20 levels, it should stop.
    # level0_level1_..._level19 will be processed.
    # When processing level19's value (which is level20: ...), depth is 19.
    # It adds (level20: ..., "level0_..._level19", 20) to stack.
    # Then it pops it. depth is 20.
    # level20 is a dict. depth is NOT < MAX_DEPTH (20).
    # So it sets result["level0_..._level19_level20"] = "[Max depth reached]"

    expected_key = "_".join([f"level{i}" for i in range(MAX_DEPTH + 1)])
    assert expected_key in flattened
    assert flattened[expected_key] == "[Max depth reached]"

    # Ensure no deeper keys exist
    deeper_key = "_".join([f"level{i}" for i in range(MAX_DEPTH + 2)])
    assert deeper_key not in flattened

def test_flatten_dict_normal_depth():
    """Verify that flatten_dict works normally for shallow nesting."""
    nested = {"a": {"b": {"c": "val"}}}
    flattened = flatten_dict(nested)
    assert flattened == {"a_b_c": "val"}
