import codecs
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional

from loguru import logger


class EncodingStrategy(Enum):
    """Defines different strategies for handling problematic characters during string sanitization"""

    REMOVE = "remove"
    REPLACE = "replace"
    ENCODE_ESCAPE = "encode_escape"
    NORMALIZE = "normalize"


@dataclass
class ConversionResult:
    """Result object containing sanitized text and conversion metadata"""

    text: str
    original_encoding: Optional[str]
    modifications: dict[str, int]  # maps modification type to occurrence count
    warnings: list[str]
    success: bool


class StringSanitizer:
    """
    A comprehensive string sanitizer that handles encoding issues, malformed characters,
    and provides various sanitization strategies with detailed tracking of modifications.
    """

    def __init__(self):
        # Control characters (0x00-0x1F) excluding newline, carriage return, and tab
        self.control_chars = set(range(0x00, 0x20)) - {0x0A, 0x0D, 0x09}
        # UTF-16 surrogate pair range (0xD800-0xDFFF)
        self.surrogate_range = set(range(0xD800, 0xE000))
        # Unicode replacement characters
        self.replacement_chars = {"\ufffd", "�"}

        # Common problematic patterns
        self.utf16_pattern = re.compile(r"\\u0000.")
        self.unicode_escape_pattern = re.compile(r"\\u[0-9a-fA-F]{4}")

        # Map of characters that should always be replaced
        self.char_replacements = {
            "\x00": "",  # null byte
            "\ufeff": "",  # byte order mark
        }

    def detect_encoding_info(self, text: str) -> dict:
        """
        Detect detailed encoding information about the string.
        """
        info = {
            "has_utf16": bool(self.utf16_pattern.search(text)),
            "has_replacement_chars": any(c in text for c in self.replacement_chars),
            "has_surrogate_pairs": any(ord(c) in self.surrogate_range for c in text),
            "has_control_chars": any(ord(c) in self.control_chars for c in text),
            "has_unicode_escapes": bool(self.unicode_escape_pattern.search(text)),
            "max_ordinal": max((ord(c) for c in text), default=0),
            "unique_chars": len(set(text)),
            "suspicious_sequences": [],
        }

        # Look for suspicious byte sequences
        try:
            encoded = text.encode("utf-8")
            if b"\xef\xbf\xbd" in encoded:  # UTF-8 replacement character
                info["suspicious_sequences"].append("utf8_replacement")  # type: ignore
        except UnicodeEncodeError:
            info["suspicious_sequences"].append("encode_error")  # type: ignore

        return info

    def normalize_string(
        self, text: str, form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFKC"
    ) -> str:
        """
        Normalize Unicode strings to a consistent form.

        Args:
            text: Input string
            form: Normalization form ('NFC', 'NFKC', 'NFD', 'NFKD')

        Returns:
            str: Normalized string
        """
        try:
            return unicodedata.normalize(form, text)
        except Exception as e:
            logger.warning(f"Normalization failed: {e}")
            return text

    def sanitize(
        self,
        text: str,
        strategy: EncodingStrategy = EncodingStrategy.NORMALIZE,
        force_encoding: Optional[str] = None,
        max_length: Optional[int] = None,
        strict: bool = False,
    ) -> ConversionResult:
        """
        Sanitize string with detailed tracking and flexible handling.

        Args:
            text: Input string
            strategy: How to handle unknown characters
            force_encoding: Optional specific encoding to use
            max_length: Optional maximum length limit
            strict: If True, raise error on any issues; if False, try to recover

        Returns:
            ConversionResult: Conversion result with metadata
        """
        if not text:
            return ConversionResult(
                text="",
                original_encoding=None,
                modifications={},
                warnings=[],
                success=True,
            )

        modifications: dict = {}
        warnings = []
        result = text

        try:
            # Detect encoding issues
            encoding_info = self.detect_encoding_info(text)

            # Track modifications
            def track_mod(mod_type: str):
                modifications[mod_type] = modifications.get(mod_type, 0) + 1

            # Handle UTF-16 sequences
            if encoding_info["has_utf16"]:
                track_mod("utf16_conversion")
                result = self.utf16_pattern.sub(lambda m: m.group(0)[-1], result)

            # Handle replacement characters
            if encoding_info["has_replacement_chars"]:
                track_mod("replacement_removal")
                for char in self.replacement_chars:
                    result = result.replace(char, "")

            # Apply normalization
            if strategy == EncodingStrategy.NORMALIZE:
                track_mod("normalization")
                result = self.normalize_string(result)

            # Handle known problematic characters
            for char, replacement in self.char_replacements.items():
                if char in result:
                    track_mod("known_char_replacement")
                    result = result.replace(char, replacement)

            # Handle control characters
            if encoding_info["has_control_chars"]:
                track_mod("control_char_handling")
                result = "".join(c for c in result if ord(c) not in self.control_chars)

            # Handle Unicode escapes
            if encoding_info["has_unicode_escapes"]:
                track_mod("unicode_escape_handling")
                try:
                    result = codecs.decode(result, "unicode-escape")
                except Exception as e:
                    warnings.append(f"Unicode escape handling failed: {e}")

            # Enforce length limit if specified
            if max_length and len(result) > max_length:
                track_mod("length_truncation")
                result = result[:max_length]

            # Final normalization pass
            result = result.strip()

            # Validate result
            if not result.isprintable() and strict:
                raise ValueError("Result contains non-printable characters")

            return ConversionResult(
                text=result,
                original_encoding=force_encoding or self._guess_encoding(encoding_info),
                modifications=modifications,
                warnings=warnings,
                success=True,
            )

        except Exception as e:
            logger.error(f"String sanitization failed: {e}")
            if strict:
                raise
            return ConversionResult(
                text=text,
                original_encoding=None,
                modifications=modifications,
                warnings=[*warnings, str(e)],
                success=False,
            )

    def _guess_encoding(self, encoding_info: dict) -> str:
        """Guess the original encoding based on string characteristics"""
        if encoding_info["has_utf16"]:
            return "utf-16"
        if encoding_info["has_surrogate_pairs"]:
            return "utf-16le"
        if encoding_info["max_ordinal"] > 127:
            return "utf-8"
        return "ascii"

    @staticmethod
    def is_safe_for_xml(text: str) -> bool:
        """Check if string is safe for XML content"""
        return all(
            0x20 <= ord(char) <= 0xD7FF
            or 0xE000 <= ord(char) <= 0xFFFD
            or 0x10000 <= ord(char) <= 0x10FFFF
            for char in text
        )
