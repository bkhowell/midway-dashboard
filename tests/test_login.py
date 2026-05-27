import pytest
from login import get_load, get_user_usage


def test_get_user_usage_a_dict():
    result = get_user_usage()
    assert isinstance(result, dict)

def test_get_user_usage_key_a_str():
    result = get_user_usage()
    for key in result.keys():
        assert isinstance(key, str)

def test_get_user_usage_value_key_check():
    required = set(["cpu", "mem", "process_count"])
    result = get_user_usage()
    for inner in result.values():
        assert set(inner.keys()) == required

def test_get_user_usage_inner_values_type():
    result = get_user_usage()
    for inner in result.values():
        assert isinstance (inner["cpu"], float)
        assert isinstance (inner["mem"], float)
        assert isinstance (inner["process_count"], int)

def test_get_user_usage_values_are_non_negative():
    result = get_user_usage()
    for inner in result.values():
         assert all( v >=0 for v in inner.values())

def test_get_user_usage_excludes_root():
    result = get_user_usage()
    assert "root" not in result



def test_get_load_returns_a_tuple():
    result = get_load()
    assert isinstance(result, tuple)

def test_get_load_returns_three_values():
    result = get_load()
    assert len(result) == 3

def test_get_load_values_are_floats():
    result = get_load()
    assert all(isinstance(x, float) for x in result)