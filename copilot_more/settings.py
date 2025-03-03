"""
Settings module for copilot-more using pydantic-settings for configuration management.
"""

import json
import os
import sys
from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, NonNegativeFloat, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from copilot_more.rate_limit_types import RateLimitBehavior


class RateLimitSettings(BaseModel):
    """Rate limit settings for a specific time window"""

    window_minutes: int = Field(..., gt=0, description="Time window in minutes")
    input_tokens: Optional[int] = Field(
        None, gt=0, description="Max input tokens in window"
    )
    output_tokens: Optional[int] = Field(
        None, gt=0, description="Max output tokens in window"
    )
    total_tokens: Optional[int] = Field(
        None, gt=0, description="Max total tokens in window"
    )
    requests: Optional[int] = Field(None, gt=0, description="Max requests in window")
    behavior: RateLimitBehavior = Field(
        default=RateLimitBehavior.ERROR,
        description="What to do when limit is hit: error or delay",
    )


class Settings(BaseSettings):
    """
    Application settings using pydantic-settings for validation and environment variable loading.

    This centralizes all configuration values and provides validation.
    """

    # GitHub Copilot API settings
    refresh_token: str = Field(
        default="", description="GitHub Copilot refresh token for authentication"
    )

    chat_completions_api_endpoint: str = Field(
        default="https://api.individual.githubcopilot.com/chat/completions",
        description="GitHub Copilot chat completions API endpoint",
    )
    models_api_endpoint: str = Field(
        default="https://api.individual.githubcopilot.com/models",
        description="GitHub Copilot models API endpoint",
    )
    editor_version: str = Field(
        default="vscode/1.97.2", description="Editor version to use in API requests"
    )

    # Request and response settings
    max_tokens: int = Field(
        default=10240, description="Maximum number of tokens in API responses"
    )
    timeout_seconds: int = Field(
        default=300, description="Timeout for API requests in seconds"
    )

    # Proxy and traffic recording settings
    record_traffic: bool = Field(
        default=False, description="Whether to record API traffic for debugging"
    )

    # Rate limiting settings from external JSON file
    rate_limits: Dict[str, List[RateLimitSettings]] = Field(
        default_factory=lambda: Settings._load_rate_limits(),
        description="Rate limits configuration per model",
    )

    @staticmethod
    def _load_rate_limits() -> Dict[str, List[RateLimitSettings]]:
        """Load rate limits from external JSON file"""
        converted_limits: Dict[str, List[RateLimitSettings]] = {}
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "rate_limits.json"
            )
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    rate_limits_data = json.load(f)

                # Convert the loaded data to RateLimitSettings objects
                for model, limits in rate_limits_data.items():
                    converted_limits[model] = [
                        RateLimitSettings(
                            window_minutes=limit["window_minutes"],
                            total_tokens=limit.get("total_tokens"),
                            input_tokens=limit.get("input_tokens"),
                            output_tokens=limit.get("output_tokens"),
                            requests=limit.get("requests"),
                            behavior=RateLimitBehavior(limit.get("behavior").lower()),
                        )
                        for limit in limits
                    ]
                print(f"Loaded rate limits from {config_path}", file=sys.stderr)
            else:
                print(
                    f"No rate limits file found at {config_path}. Rate limiting is disabled.",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"Failed to load rate limits from {config_path}: {str(e)}. No rate limits will be applied.",
                file=sys.stderr,
            )

        return converted_limits

    # Deprecated: Random delay settings for throttling
    min_delay_seconds: NonNegativeFloat = Field(
        default=0.0,
        description="[Deprecated] Minimum random delay time in seconds",
    )
    max_delay_seconds: NonNegativeFloat = Field(
        default=0.0,
        description="[Deprecated] Maximum random delay time in seconds",
    )

    # Logging settings
    loguru_level: str = Field(
        default="INFO", description="Loguru logging level (default: INFO)"
    )

    # Sleep setting between API calls
    sleep_between_calls: NonNegativeFloat = Field(
        default=0.0,
        description="Sleep duration in seconds between API calls",
    )

    # Pydantic model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("refresh_token")
    def validate_refresh_token(cls, v: str) -> str:
        """Validate that the refresh token is provided and starts with 'gho_'."""
        if not v:
            raise ValueError("REFRESH_TOKEN environment variable is required")

        if not v.startswith("gho_"):
            raise ValueError(
                "REFRESH_TOKEN should be a GitHub OAuth token starting with 'gho_'"
            )
        return v

    @field_validator("max_delay_seconds")
    def validate_max_delay(cls, v: float, info) -> float:
        """Validate that max_delay_seconds is >= min_delay_seconds."""
        min_delay = info.data.get("min_delay_seconds", 0.0)
        if v < min_delay:
            raise ValueError(
                "max_delay_seconds must be greater than or equal to min_delay_seconds"
            )
        return v


@lru_cache()
def get_settings() -> Settings:
    """
    Get the application settings.

    Using a function with lru_cache allows for lazy loading and efficient reuse.
    """
    settings = Settings()

    # Initialize logger with configured level
    from copilot_more.logger import init_logger

    init_logger(settings.loguru_level)

    return settings


# Create a global instance for direct import in most cases
settings = get_settings()
