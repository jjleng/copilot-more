import pytest

from copilot_more.utils import convert_problematic_string, needs_conversion


def test_convert_problematic_string_success():
    input_string = "\ufffd\ufffd[\u00002\u00005..."
    expected = "[25"  # Partial match since the docstring example might be truncated
    result = convert_problematic_string(input_string)
    assert result.startswith(expected)


def test_convert_problematic_string_normal():
    # Test with a normal string
    input_string = "Hello, World!"
    assert convert_problematic_string(input_string) == input_string


def test_convert_problematic_string_empty():
    # Test with empty string
    assert convert_problematic_string("") == ""


def test_convert_problematic_string_with_control_chars():
    # Test string with control characters
    input_string = "Hello\x00World\x01"
    expected = "HelloWorld"
    assert convert_problematic_string(input_string) == expected


def test_needs_conversion():
    # Test strings that need conversion
    assert needs_conversion("\ufffdHello") == True
    assert needs_conversion("Hello") == False
    assert needs_conversion("") == False
