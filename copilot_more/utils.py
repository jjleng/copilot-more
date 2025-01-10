from copilot_more.logger import logger


def convert_problematic_string(input_string: str) -> str:
    """
    Converts a problematic UTF-16 string with invalid characters to a clean, readable format.

    Example:
        >>> s = "\ufffd\ufffd[\u00002\u00005..."
        >>> convert_problematic_string(s)
        '[25/01/09][09:23:50] Logging ON'
    """
    try:
        # Remove the replacement characters (�)
        cleaned: str = input_string.replace("\ufffd", "")

        # Convert the UTF-16 escape sequences to actual characters
        decoded: str = ""
        i: int = 0

        while i < len(cleaned):
            if cleaned[i : i + 6].startswith("\\u0000"):
                # Extract the actual character and skip the UTF-16 encoding
                char: str = cleaned[i + 6]
                decoded += char
                i += 7
            else:
                # Keep other characters as is
                decoded += cleaned[i]
                i += 1

        # Remove any remaining control characters
        decoded = "".join(char for char in decoded if ord(char) >= 32 or char in "\n\r")

        return decoded.strip()
    except Exception as e:
        logger.error(f"Error converting problematic string: {str(e)}")
        return input_string


def needs_conversion(s: str) -> bool:
    """
    Check if a string contains problematic characters that need conversion.
    """
    # '\ufffd' is the Unicode replacement character, used when an encoding is interpreted as another encoding and certain characters cannot be recognized
    # UTF-16 files often include a Byte Order Mark (BOM), a two-byte sequence at the start of the file, which can cause issues if the file is incorrectly read as UTF-8 or ASCII
    # In Windows PowerShell, the terminal typically outputs text in UTF-16 encoding. However, when tools like Cline/RooCline interpret the output as UTF-8, misinterpretation occurs, leading to invalid characters being replaced with '\ufffd'
    return "\ufffd" in s
