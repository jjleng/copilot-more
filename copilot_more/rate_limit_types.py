from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Maximum delay that can be applied for rate limiting (in seconds)
# This prevents excessive delays while still maintaining rate limiting effectiveness
MAX_DELAY_SECONDS = 60


class RateLimitBehavior(Enum):
    ERROR = "error"  # Raise error when limit is hit
    DELAY = "delay"  # Delay request to stay within limits


@dataclass
class RateLimitRule:
    window_minutes: int  # Time window in minutes
    input_tokens: Optional[int] = None  # Max input tokens in window
    output_tokens: Optional[int] = None  # Max output tokens in window
    total_tokens: Optional[int] = None  # Max total tokens in window
    requests: Optional[int] = None  # Max requests in window
    behavior: RateLimitBehavior = RateLimitBehavior.ERROR
