from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from copilot_more.rate_limit_types import (MAX_DELAY_SECONDS,
                                           RateLimitBehavior, RateLimitRule)
from copilot_more.rate_limiter import RateLimiter, RateLimitError
from copilot_more.token_counter import TokenUsage


@pytest.fixture
def token_usage():
    return Mock(spec=TokenUsage)


@pytest.fixture
def rate_limiter(token_usage):
    return RateLimiter(token_usage)


@pytest.fixture
def test_model():
    return "test-model"


@pytest.fixture
def base_time():
    return datetime(2025, 1, 1, 12, 0, 0)  # Noon on Jan 1st, 2025


@pytest.mark.asyncio
async def test_sliding_window_request_limits(rate_limiter, test_model, base_time):
    """Test sliding window behavior for request rate limiting."""
    # Create a rule: max 3 requests per 5 minutes
    rule = RateLimitRule(window_minutes=5, requests=3, behavior=RateLimitBehavior.ERROR)
    rate_limiter.add_rule(test_model, rule)

    # Make 3 requests at different times within the window
    current_time = base_time
    rate_limiter.record_request(test_model, current_time)
    rate_limiter.record_request(test_model, current_time + timedelta(minutes=1))
    rate_limiter.record_request(test_model, current_time + timedelta(minutes=2))

    # Fourth request should fail
    with pytest.raises(RateLimitError):
        await rate_limiter.check_request_limit(
            test_model, current_time + timedelta(minutes=3)
        )

    # After 6 minutes from the first request, the earliest request should be out of the window
    # allowing a new request
    new_time = current_time + timedelta(minutes=6)
    result = await rate_limiter.check_request_limit(test_model, new_time)
    assert result is None


@pytest.mark.asyncio
async def test_sliding_window_token_limits(
    rate_limiter, test_model, base_time, token_usage
):
    """Test sliding window behavior for token rate limiting."""
    # Create a rule: max 1000 tokens per 5 minutes
    rule = RateLimitRule(
        window_minutes=5, total_tokens=1000, behavior=RateLimitBehavior.ERROR
    )
    rate_limiter.add_rule(test_model, rule)

    # Mock token usage response
    token_usage.query_usage.return_value = {
        "total_input_tokens": 600,
        "total_output_tokens": 400,
        "total_tokens": 1000,
    }

    # Check token limits - should hit the limit exactly
    current_time = base_time
    result = rate_limiter.check_token_limits(test_model, current_time)
    assert result is None

    # Increase usage above limit
    token_usage.query_usage.return_value = {
        "total_input_tokens": 700,
        "total_output_tokens": 500,
        "total_tokens": 1200,
    }

    # Should raise error as we're over the limit
    with pytest.raises(RateLimitError):
        rate_limiter.check_token_limits(test_model, current_time)


@pytest.mark.asyncio
async def test_delay_behavior(rate_limiter, test_model, base_time):
    """Test delay behavior for rate limiting."""
    # Create a rule with DELAY behavior
    rule = RateLimitRule(window_minutes=5, requests=2, behavior=RateLimitBehavior.DELAY)
    rate_limiter.add_rule(test_model, rule)

    current_time = base_time

    # Make initial requests
    rate_limiter.record_request(test_model, current_time)
    rate_limiter.record_request(test_model, current_time + timedelta(minutes=1))

    # Third request should require delay
    delay = await rate_limiter.check_request_limit(
        test_model, current_time + timedelta(minutes=2)
    )
    assert delay is not None
    assert delay > 0


@pytest.mark.asyncio
async def test_combined_limits(rate_limiter, test_model, base_time, token_usage):
    """Test combined token and request rate limiting."""
    # Create rules for both tokens and requests
    token_rule = RateLimitRule(
        window_minutes=5, total_tokens=1000, behavior=RateLimitBehavior.ERROR
    )
    request_rule = RateLimitRule(
        window_minutes=5, requests=3, behavior=RateLimitBehavior.ERROR
    )
    rate_limiter.add_rule(test_model, token_rule)
    rate_limiter.add_rule(test_model, request_rule)

    current_time = base_time

    # Mock token usage below limit
    token_usage.query_usage.return_value = {
        "total_input_tokens": 400,
        "total_output_tokens": 300,
        "total_tokens": 700,
    }

    # Make requests up to the request limit
    rate_limiter.record_request(test_model, current_time)
    rate_limiter.record_request(test_model, current_time + timedelta(minutes=1))
    rate_limiter.record_request(test_model, current_time + timedelta(minutes=2))

    # Should fail on request limit even though token limit is fine
    with pytest.raises(RateLimitError):
        next_time = current_time + timedelta(minutes=3)
        # Check limit first - should fail since we already have 3 requests
        await rate_limiter.check_request_limit(test_model, next_time)
        # This line shouldn't be reached since check_request_limit should raise
        rate_limiter.record_request(test_model, next_time)

    # Now test token limit
    token_usage.query_usage.return_value = {
        "total_input_tokens": 600,
        "total_output_tokens": 500,
        "total_tokens": 1100,
    }

    # Should fail on token limit
    with pytest.raises(RateLimitError):
        rate_limiter.check_token_limits(test_model, current_time)


def test_token_delay_cap(rate_limiter, test_model, base_time, token_usage):
    """Test that token-based delays are properly capped."""

    # Create a rule with DELAY behavior and large window/limits to potentially cause large delays
    rule = RateLimitRule(
        window_minutes=120,  # 2 hour window
        total_tokens=1000,
        behavior=RateLimitBehavior.DELAY,
    )
    rate_limiter.add_rule(test_model, rule)

    # Set usage to 2x the limit which would normally cause a huge delay
    token_usage.query_usage.return_value = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 2000,  # 200% of limit
    }

    # Check token limits - should return a capped delay
    current_time = base_time
    delay = rate_limiter.check_token_limits(test_model, current_time)

    assert delay is not None
    assert delay <= MAX_DELAY_SECONDS
