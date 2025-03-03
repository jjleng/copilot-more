"""
Tests for the settings module.
"""

import json
import os
from pathlib import Path
from unittest import TestCase, mock

import pytest
from pydantic import ValidationError

# Ensure we don't trigger the validation when importing for tests
with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_test_token_for_import"}):
    from copilot_more.settings import Settings

from copilot_more.rate_limit_types import RateLimitBehavior


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

    def test_rate_limits_loading(self):
        """Test loading of rate limits from JSON file."""
        test_limits = {
            "test-model": [
                {
                    "window_minutes": 1,
                    "total_tokens": 1000,
                    "input_tokens": 500,
                    "output_tokens": 500,
                    "requests": 5,
                    "behavior": "delay",
                }
            ]
        }

        # Mock everything needed for rate limits loading
        mock_open = mock.mock_open(read_data=json.dumps(test_limits))
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            with mock.patch("builtins.open", mock_open):
                with mock.patch("os.path.exists") as mock_exists:
                    mock_exists.return_value = True
                    settings = Settings()

                    # Verify rate limits loaded correctly
                    assert "test-model" in settings.rate_limits
                    limits = settings.rate_limits["test-model"]
                    assert len(limits) == 1
                    limit = limits[0]
                    assert limit.window_minutes == 1
                    assert limit.total_tokens == 1000
                    assert limit.input_tokens == 500
                    assert limit.output_tokens == 500
                    assert limit.requests == 5
                    assert limit.behavior == RateLimitBehavior.DELAY

    def test_rate_limits_file_not_found(self):
        """Test behavior when rate limits file is not found."""
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            with mock.patch("os.path.exists") as mock_exists:
                mock_exists.return_value = False
                settings = Settings()
                assert settings.rate_limits == {}

    def test_rate_limits_invalid_json(self):
        """Test behavior with invalid JSON in rate limits file."""
        mock_open = mock.mock_open(read_data="invalid json")
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            with mock.patch("builtins.open", mock_open):
                with mock.patch("os.path.exists") as mock_exists:
                    mock_exists.return_value = True
                    settings = Settings()
                    assert settings.rate_limits == {}

    def test_rate_limits_invalid_schema(self):
        """Test validation of rate limits schema."""
        invalid_limits = {
            "test-model": [
                {
                    "window_minutes": -1,  # Invalid: must be positive
                    "behavior": "invalid",  # Invalid: must be delay or error
                }
            ]
        }

        mock_open = mock.mock_open(read_data=json.dumps(invalid_limits))
        with mock.patch.dict(os.environ, {"REFRESH_TOKEN": "gho_valid_token"}):
            with mock.patch("builtins.open", mock_open):
                with mock.patch("os.path.exists") as mock_exists:
                    mock_exists.return_value = True
                    settings = Settings()
                    assert settings.rate_limits == {}
