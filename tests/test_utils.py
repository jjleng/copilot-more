from typing import Any

import pytest

from copilot_more.utils import (ConversionResult, EncodingStrategy,
                                StringSanitizer)


@pytest.fixture
def sanitizer() -> StringSanitizer:
    """Create a fresh StringSanitizer instance for each test"""
    return StringSanitizer()


def test_sanitize_normal_string(sanitizer: StringSanitizer) -> None:
    # Use REMOVE strategy to avoid automatic normalization
    result: ConversionResult = sanitizer.sanitize(
        "Hello, World!", strategy=EncodingStrategy.REMOVE
    )
    assert result.text == "Hello, World!"
    assert result.success
    assert not result.modifications
    assert not result.warnings


def test_sanitize_empty_string(sanitizer: StringSanitizer) -> None:
    result: ConversionResult = sanitizer.sanitize("")
    assert result.text == ""
    assert result.success
    assert not result.modifications
    assert not result.warnings
    assert result.original_encoding is None


def test_sanitize_with_control_chars(sanitizer: StringSanitizer) -> None:
    result: ConversionResult = sanitizer.sanitize("Hello\x00World\x01")
    assert result.text == "HelloWorld"
    assert result.success
    assert "control_char_handling" in result.modifications
    assert result.modifications["control_char_handling"] == 1


def test_sanitize_with_replacement_chars(sanitizer: StringSanitizer) -> None:
    result: ConversionResult = sanitizer.sanitize("Hello\ufffdWorld")
    assert result.text == "HelloWorld"
    assert result.success
    assert "replacement_removal" in result.modifications
    assert result.modifications["replacement_removal"] == 1


def test_sanitize_with_max_length(sanitizer: StringSanitizer) -> None:
    result: ConversionResult = sanitizer.sanitize("Hello World", max_length=5)
    assert result.text == "Hello"
    assert result.success
    assert "length_truncation" in result.modifications


def test_sanitize_with_different_strategies(sanitizer: StringSanitizer) -> None:
    text: str = "Hello\ufffdWorld"

    # Test NORMALIZE strategy
    norm_result: ConversionResult = sanitizer.sanitize(
        text, strategy=EncodingStrategy.NORMALIZE
    )
    assert norm_result.success
    assert "normalization" in norm_result.modifications

    # Test REMOVE strategy
    remove_result: ConversionResult = sanitizer.sanitize(
        text, strategy=EncodingStrategy.REMOVE
    )
    assert remove_result.success
    assert remove_result.text == "HelloWorld"


def test_sanitize_with_strict_mode(sanitizer: StringSanitizer) -> None:
    # Use a character that's not in control_chars but still non-printable
    text: str = "Hello\u2028World"  # LINE SEPARATOR

    # Non-strict mode should succeed and keep the character
    result: ConversionResult = sanitizer.sanitize(text, strict=False)
    assert result.success
    assert "\u2028" in result.text

    # Strict mode should fail since the result contains non-printable characters
    with pytest.raises(ValueError):
        sanitizer.sanitize(text, strict=True)


def test_detect_encoding_info(sanitizer: StringSanitizer) -> None:
    text: str = "Hello\ufffdWorld\u0000"
    info: dict[str, Any] = sanitizer.detect_encoding_info(text)

    assert info["has_replacement_chars"]
    assert info["has_control_chars"]
    assert isinstance(info["max_ordinal"], int)
    assert isinstance(info["unique_chars"], int)


def test_normalize_string(sanitizer: StringSanitizer) -> None:
    # Test with combining characters
    text: str = "e\u0301"  # é composed of 'e' and combining acute accent
    result: str = sanitizer.normalize_string(text, form="NFC")
    assert len(result) == 1  # Should combine into a single character
    assert result == "é"


def test_is_safe_for_xml(sanitizer: StringSanitizer) -> None:
    # Test valid XML characters
    assert sanitizer.is_safe_for_xml("Hello World")

    # Test invalid XML characters
    assert not sanitizer.is_safe_for_xml("\x00Hello")  # Null byte
    assert not sanitizer.is_safe_for_xml("\uDC00")  # Surrogate pair


def test_guess_encoding(sanitizer: StringSanitizer) -> None:
    # Test ASCII text
    info: dict[str, Any] = sanitizer.detect_encoding_info("Hello")
    assert sanitizer._guess_encoding(info) == "ascii"

    # Test UTF-8 text
    info = sanitizer.detect_encoding_info("Hello 世界")
    assert sanitizer._guess_encoding(info) == "utf-8"
