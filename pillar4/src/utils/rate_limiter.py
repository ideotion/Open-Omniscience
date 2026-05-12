"""
Pillar 4: Real-Time Monitoring & Alerting System - Rate Limiter

Rate limiting utilities for API calls and resource access.
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Tuple
from collections import deque, defaultdict
import asyncio
import logging


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_requests: int  # Maximum number of requests
    period: float  # Time period in seconds
    burst_size: Optional[int] = None  # Maximum burst size (None = same as max_requests)


class RateLimiter:
    """
    Token bucket rate limiter for controlling request rates.

    Supports:
    - Fixed window rate limiting
    - Token bucket algorithm
    - Per-key rate limiting
    - Async and sync usage
    """

    def __init__(self, config: RateLimitConfig):
        """
        Initialize the rate limiter.

        Args:
            config: Rate limit configuration.
        """
        self.config = config
        self.tokens = config.max_requests
        self.last_refill = time.time()
        self.burst_size = config.burst_size if config.burst_size is not None else config.max_requests
        self.burst_tokens = self.burst_size
        self.logger = logging.getLogger("RateLimiter")

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate how many tokens to add
        tokens_to_add = (elapsed / self.config.period) * self.config.max_requests

        if tokens_to_add > 0:
            self.tokens = min(self.config.max_requests, self.tokens + tokens_to_add)
            self.burst_tokens = min(self.burst_size, self.burst_tokens + tokens_to_add)
            self.last_refill = now

    def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens for a request.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False if rate limited.
        """
        self._refill()

        if self.tokens >= tokens and self.burst_tokens >= tokens:
            self.tokens -= tokens
            self.burst_tokens -= tokens
            return True

        return False

    def wait(self, tokens: int = 1) -> float:
        """
        Wait until tokens are available.

        Args:
            tokens: Number of tokens to wait for.

        Returns:
            Time waited in seconds.
        """
        start = time.time()

        while not self.acquire(tokens):
            self._refill()
            wait_time = self.config.period * (tokens - self.tokens) / self.config.max_requests
            if wait_time > 0:
                time.sleep(min(wait_time, 0.1))  # Sleep in small increments

        return time.time() - start

    def get_available(self) -> int:
        """Get the number of available tokens."""
        self._refill()
        return min(int(self.tokens), int(self.burst_tokens))

    def get_wait_time(self, tokens: int = 1) -> float:
        """
        Get the estimated wait time for tokens.

        Args:
            tokens: Number of tokens needed.

        Returns:
            Estimated wait time in seconds.
        """
        self._refill()

        if self.tokens >= tokens and self.burst_tokens >= tokens:
            return 0.0

        tokens_needed = tokens - min(self.tokens, self.burst_tokens)
        return (tokens_needed / self.config.max_requests) * self.config.period


class MultiKeyRateLimiter:
    """
    Rate limiter with support for multiple keys (e.g., per-API-key rate limiting).
    """

    def __init__(self, default_config: RateLimitConfig):
        """
        Initialize the multi-key rate limiter.

        Args:
            default_config: Default rate limit configuration for new keys.
        """
        self.default_config = default_config
        self.limiters: Dict[str, RateLimiter] = {}
        self.key_configs: Dict[str, RateLimitConfig] = {}
        self.logger = logging.getLogger("MultiKeyRateLimiter")

    def add_key(self, key: str, config: Optional[RateLimitConfig] = None) -> None:
        """
        Add a new key with its own rate limit.

        Args:
            key: Key identifier.
            config: Rate limit configuration for this key (defaults to default_config).
        """
        if config is None:
            config = self.default_config

        self.key_configs[key] = config
        self.limiters[key] = RateLimiter(config)
        self.logger.debug(f"Added rate limit key: {key}")

    def remove_key(self, key: str) -> bool:
        """Remove a key."""
        if key in self.limiters:
            del self.limiters[key]
            del self.key_configs[key]
            self.logger.debug(f"Removed rate limit key: {key}")
            return True
        return False

    def acquire(self, key: str, tokens: int = 1) -> bool:
        """
        Acquire tokens for a specific key.

        Args:
            key: Key identifier.
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False if rate limited.
        """
        if key not in self.limiters:
            self.add_key(key)

        return self.limiters[key].acquire(tokens)

    def wait(self, key: str, tokens: int = 1) -> float:
        """
        Wait for tokens for a specific key.

        Args:
            key: Key identifier.
            tokens: Number of tokens to wait for.

        Returns:
            Time waited in seconds.
        """
        if key not in self.limiters:
            self.add_key(key)

        return self.limiters[key].wait(tokens)

    def get_available(self, key: str) -> int:
        """Get available tokens for a key."""
        if key not in self.limiters:
            return self.default_config.max_requests
        return self.limiters[key].get_available()

    def get_wait_time(self, key: str, tokens: int = 1) -> float:
        """Get wait time for tokens for a key."""
        if key not in self.limiters:
            return 0.0
        return self.limiters[key].get_wait_time(tokens)

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "total_keys": len(self.limiters),
            "default_config": {
                "max_requests": self.default_config.max_requests,
                "period": self.default_config.period,
            },
            "keys": {
                key: {
                    "available": limiter.get_available(),
                    "config": {
                        "max_requests": config.max_requests,
                        "period": config.period,
                    },
                }
                for key, (limiter, config) in zip(self.limiters.keys(), self.key_configs.values())
            },
        }


class AsyncRateLimiter:
    """
    Async-compatible rate limiter.
    """

    def __init__(self, config: RateLimitConfig):
        """
        Initialize the async rate limiter.

        Args:
            config: Rate limit configuration.
        """
        self.config = config
        self.tokens = config.max_requests
        self.last_refill = time.time()
        self.burst_size = config.burst_size if config.burst_size is not None else config.max_requests
        self.burst_tokens = self.burst_size
        self.lock = asyncio.Lock()
        self.logger = logging.getLogger("AsyncRateLimiter")

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate how many tokens to add
        tokens_to_add = (elapsed / self.config.period) * self.config.max_requests

        if tokens_to_add > 0:
            self.tokens = min(self.config.max_requests, self.tokens + tokens_to_add)
            self.burst_tokens = min(self.burst_size, self.burst_tokens + tokens_to_add)
            self.last_refill = now

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens for a request (async version).

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False if rate limited.
        """
        async with self.lock:
            await self._refill()

            if self.tokens >= tokens and self.burst_tokens >= tokens:
                self.tokens -= tokens
                self.burst_tokens -= tokens
                return True

            return False

    async def wait(self, tokens: int = 1) -> float:
        """
        Wait until tokens are available (async version).

        Args:
            tokens: Number of tokens to wait for.

        Returns:
            Time waited in seconds.
        """
        start = time.time()

        while not await self.acquire(tokens):
            async with self.lock:
                await self._refill()
                wait_time = self.config.period * (tokens - self.tokens) / self.config.max_requests

            if wait_time > 0:
                await asyncio.sleep(min(wait_time, 0.1))

        return time.time() - start

    def get_available(self) -> int:
        """Get the number of available tokens."""
        # Note: This is not thread-safe, but provides a rough estimate
        return min(int(self.tokens), int(self.burst_tokens))

    def get_wait_time(self, tokens: int = 1) -> float:
        """Get the estimated wait time for tokens."""
        # Note: This is not thread-safe, but provides a rough estimate
        if self.tokens >= tokens and self.burst_tokens >= tokens:
            return 0.0

        tokens_needed = tokens - min(self.tokens, self.burst_tokens)
        return (tokens_needed / self.config.max_requests) * self.config.period
