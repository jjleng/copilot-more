"""
Tests for the settings module.
"""

import os
from unittest import TestCase, mock

import pytest
from pydantic import ValidationError

# Ensure we don't trigger the validation when importing for tests
with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_test_token_for_import"}):
    from copilot_more.settings import Settings


class TestSettings(TestCase):
    """Tests for the Settings class."""

    def setUp(self):
        # Clear any environment variables that might affect tests
        os.environ.pop("REFRESH_TOKEN", None)
        os.environ.pop("CHAT_COMPLETIONS_API_ENDPOINT", None)
        os.environ.pop("MODELS_API_ENDPOINT", None)
        os.environ.pop("EDITOR_VERSION", None)
        os.environ.pop("MAX_TOKENS", None)
        os.environ.pop("TIMEOUT_SECONDS", None)
        os.environ.pop("RECORD_TRAFFIC", None)

    def test_refresh_token_validation(self):
        """Test that refresh token is validated."""
        # Must start with gho_
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "invalid_token"}):
            with pytest.raises(ValidationError) as excinfo:
                Settings()
            assert (
                "REFRESH_TOKEN should be a GitHub OAuth token starting with 'gho_'"
                in str(excinfo.value)
            )

        # Valid token
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            settings = Settings()
            assert settings.refresh_token == "gho_valid_token"

    def test_default_values(self):
        """Test that default values are set correctly."""
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            settings = Settings()
            assert (
                settings.chat_completions_api_endpoint
                == "https://api.individual.githubcopilot.com/chat/completions"
            )
            assert (
                settings.models_api_endpoint
                == "https://api.individual.githubcopilot.com/models"
            )
            assert settings.editor_version == "vscode/1.97.2"
            assert settings.max_tokens == 10240
            assert settings.timeout_seconds == 300
            assert settings.record_traffic is False

    def test_custom_values(self):
        """Test that custom values can be set."""
        with mock.patch.dict(
            os.environ,
            {
                "REFRESH_TOKEN": "gho_valid_token",
                "CHAT_COMPLETIONS_API_ENDPOINT": "https://custom.endpoint/chat",
                "MODELS_API_ENDPOINT": "https://custom.endpoint/models",
                "EDITOR_VERSION": "custom-editor/1.0",
                "MAX_TOKENS": "5000",
                "TIMEOUT_SECONDS": "600",
                "RECORD_TRAFFIC": "true",
            },
        ):
            settings = Settings()
            assert (
                settings.chat_completions_api_endpoint == "https://custom.endpoint/chat"
            )
            assert settings.models_api_endpoint == "https://custom.endpoint/models"
            assert settings.editor_version == "custom-editor/1.0"
            assert settings.max_tokens == 5000
            assert settings.timeout_seconds == 600
            assert settings.record_traffic is True

    def test_boolean_conversion(self):
        """Test that boolean values are converted correctly."""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
        ]

        for value, expected in test_cases:
            with mock.patch.dict(
                os.environ,
                {"REFRESH_TOKEN": "gho_valid_token", "RECORD_TRAFFIC": value},
            ):
                settings = Settings()
                assert settings.record_traffic is expected, f"Failed for value: {value}"
