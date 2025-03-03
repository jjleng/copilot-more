from datetime import datetime, timedelta
from typing import Dict, Optional

from copilot_more.logger import logger
from copilot_more.rate_limit_types import (MAX_DELAY_SECONDS,
                                           RateLimitBehavior, RateLimitRule)
from copilot_more.token_counter import TokenUsage


class RateLimitError(Exception):
    """Raised when rate limit is exceeded"""

    pass


class RateLimiter:
    def __init__(self, token_usage: TokenUsage):
        self.token_usage = token_usage
        self.request_counters: Dict[str, Dict[int, Dict[datetime, int]]] = {}
        self.rules: Dict[str, list[RateLimitRule]] = {}
        self.next_allowed_request: Dict[str, datetime] = (
            {}
        )  # Track when next request is allowed per model

    def add_rule(self, model: str, rule: RateLimitRule):
        """Add a rate limit rule for a model"""
        if model not in self.rules:
            self.rules[model] = []
        self.rules[model].append(rule)
        logger.info(f"Added rate limit rule for model {model}: {rule}")

    def _check_token_limits(
        self, model: str, rule: RateLimitRule, start_time: datetime, end_time: datetime
    ) -> tuple[bool, Optional[dict]]:
        """
        Check if token usage is within limits.
        Returns (is_within_limits, usage_stats)
        """
        usage = self.token_usage.query_usage(start_time, end_time, model)

        if rule.input_tokens and usage["total_input_tokens"] > rule.input_tokens:
            return False, usage
        if rule.output_tokens and usage["total_output_tokens"] > rule.output_tokens:
            return False, usage
        if rule.total_tokens and usage["total_tokens"] > rule.total_tokens:
            return False, usage

        return True, usage

    def _check_request_limits(
        self, model: str, rule: RateLimitRule, current_time: datetime
    ) -> tuple[bool, Optional[int]]:
        """
        Check if request count is within limits using a sliding window approach.
        Returns (is_within_limits, current_count)
        """
        if not rule.requests:
            return True, None

        if model not in self.request_counters:
            self.request_counters[model] = {}
        if rule.window_minutes not in self.request_counters[model]:
            self.request_counters[model][rule.window_minutes] = {}

        # Get the window start time for our sliding window
        window_start = current_time - timedelta(minutes=rule.window_minutes)

        # Clean up entries older than twice the window size to prevent memory growth
        cleanup_time = current_time - timedelta(minutes=2 * rule.window_minutes)
        self.request_counters[model][rule.window_minutes] = {
            ts: count
            for ts, count in self.request_counters[model][rule.window_minutes].items()
            if ts >= cleanup_time
        }

        # Count requests in the sliding window
        total_requests = sum(
            count
            for ts, count in self.request_counters[model][rule.window_minutes].items()
            if ts >= window_start
        )

        return total_requests < rule.requests, total_requests

    def _calculate_needed_delay(
        self, model: str, rule: RateLimitRule, current_time: datetime
    ) -> float:
        """Calculate delay needed to meet rate limits"""
        if not rule.requests:
            return 0.0

        window_start = current_time - timedelta(minutes=rule.window_minutes)
        counters = self.request_counters.get(model, {}).get(rule.window_minutes, {})

        # Sort timestamps
        sorted_times = sorted(
            [ts for ts in counters.keys() if ts >= window_start], reverse=True
        )

        if len(sorted_times) < rule.requests:
            return 0.0

        # Calculate when the oldest request in our limit will expire
        oldest_allowed = sorted_times[rule.requests - 1]
        delay = (
            oldest_allowed + timedelta(minutes=rule.window_minutes) - current_time
        ).total_seconds()
        return max(0.0, delay)

    def record_request(self, model: str, current_time: datetime):
        """Record a request for rate limiting purposes"""
        if model not in self.request_counters:
            self.request_counters[model] = {}

        for rule in self.rules.get(model, []):
            if rule.requests:
                if rule.window_minutes not in self.request_counters[model]:
                    self.request_counters[model][rule.window_minutes] = {}
                window_counters = self.request_counters[model][rule.window_minutes]
                window_counters[current_time] = window_counters.get(current_time, 0) + 1

    async def check_request_limit(
        self, model: str, current_time: datetime
    ) -> Optional[float]:
        """
        Check request rate limits for a model and return delay needed (if any).
        Raises RateLimitError if limits are exceeded and behavior is ERROR.
        Returns delay needed in seconds if any limits require delay.
        Only checks request frequency limits, not token limits.
        """
        if model not in self.rules:
            return None

        # Check if we need to wait based on previous token limit violations
        if model in self.next_allowed_request:
            if current_time < self.next_allowed_request[model]:
                delay = (
                    self.next_allowed_request[model] - current_time
                ).total_seconds()
                return max(0.0, delay)
        max_delay = 0.0

        for rule in self.rules[model]:
            # Only check request limits here
            if not rule.requests:
                continue

            within_request_limits, request_count = self._check_request_limits(
                model, rule, current_time
            )

            if not within_request_limits:
                if rule.behavior == RateLimitBehavior.ERROR:
                    raise RateLimitError(
                        f"Request limit exceeded for model {model} in {rule.window_minutes}min window. "
                        f"Requests: {request_count}/{rule.requests}"
                    )
                delay = self._calculate_needed_delay(model, rule, current_time)
                max_delay = max(max_delay, delay)

        return max_delay if max_delay > 0 else None

    def check_token_limits(self, model: str, current_time: datetime) -> Optional[float]:
        """
        Check if current token usage is within limits using a sliding window approach.
        Returns delay needed in seconds if any rate limits require delay.
        Raises RateLimitError if exceeded and behavior is ERROR.
        This should be called after each API response with actual usage data.
        """
        if model not in self.rules:
            return None

        max_delay = 0.0

        for rule in self.rules[model]:
            window_start = current_time - timedelta(minutes=rule.window_minutes)
            # Use sliding window for token usage check
            within_limits, usage = self._check_token_limits(
                model, rule, window_start, current_time
            )

            if not within_limits:
                if rule.behavior == RateLimitBehavior.ERROR:
                    raise RateLimitError(
                        f"Token rate limit exceeded for model {model} in {rule.window_minutes}min sliding window. "
                        f"Usage: {usage}"
                    )

                # Calculate a proportional delay based on current usage
                # If we're at 150% of our limit, wait for 50% of the window
                # If we're at 200% of our limit, wait for the full window
                usage_ratio = 1.0
                if usage and rule.total_tokens and usage["total_tokens"] > 0:
                    usage_ratio = usage["total_tokens"] / rule.total_tokens
                elif usage and rule.input_tokens and usage["total_input_tokens"] > 0:
                    usage_ratio = usage["total_input_tokens"] / rule.input_tokens
                elif usage and rule.output_tokens and usage["total_output_tokens"] > 0:
                    usage_ratio = usage["total_output_tokens"] / rule.output_tokens

                # Cap the ratio at 2.0 (200%) to prevent excessive delays
                usage_ratio = min(2.0, usage_ratio)

                # Calculate delay as a portion of the window size
                # but cap it at MAX_DELAY_SECONDS
                base_delay = rule.window_minutes * 60.0 * (usage_ratio - 1.0)
                delay = min(base_delay, MAX_DELAY_SECONDS)
                max_delay = max(max_delay, delay)

                # Update next allowed request time
                next_allowed = current_time + timedelta(seconds=delay)
                if model in self.next_allowed_request:
                    self.next_allowed_request[model] = max(
                        self.next_allowed_request[model], next_allowed
                    )
                else:
                    self.next_allowed_request[model] = next_allowed

        return max_delay if max_delay > 0 else None
