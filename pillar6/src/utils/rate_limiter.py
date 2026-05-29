"""
Rate Limiter Utility

Provides rate limiting functionality for web scraping.
"""

import asyncio
import time
from typing import Optional, Callable, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for controlling request frequency.
    
    Supports both synchronous and asynchronous rate limiting.
    """
    
    def __init__(
        self,
        requests_per_second: float = 2.0,
        burst_size: int = 5,
    ):
        """
        Initialize the rate limiter.
        
        Args:
            requests_per_second: Maximum requests per second
            burst_size: Maximum number of requests that can be made in a burst
        """
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self.tokens = burst_size
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()
    
    def wait(self) -> None:
        """
        Wait for the next available slot.
        
        Synchronous version for use with requests library.
        """
        current_time = time.time()
        
        # Calculate time since last request
        time_since_last = current_time - self.last_request_time
        
        # Refill tokens based on time passed
        tokens_to_add = time_since_last * self.requests_per_second
        self.tokens = min(self.burst_size, self.tokens + tokens_to_add)
        
        # If we have tokens, use one
        if self.tokens >= 1:
            self.tokens -= 1
            self.last_request_time = current_time
            return
        
        # Otherwise, wait for the next token
        wait_time = self.min_interval - time_since_last
        if wait_time > 0:
            time.sleep(wait_time)
            self.tokens = 1
            self.last_request_time = time.time()
    
    async def async_wait(self) -> None:
        """
        Wait for the next available slot (async version).
        
        Asynchronous version for use with aiohttp library.
        """
        async with self.lock:
            current_time = time.time()
            
            # Calculate time since last request
            time_since_last = current_time - self.last_request_time
            
            # Refill tokens based on time passed
            tokens_to_add = time_since_last * self.requests_per_second
            self.tokens = min(self.burst_size, self.tokens + tokens_to_add)
            
            # If we have tokens, use one
            if self.tokens >= 1:
                self.tokens -= 1
                self.last_request_time = current_time
                return
            
            # Otherwise, wait for the next token
            wait_time = self.min_interval - time_since_last
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                self.tokens = 1
                self.last_request_time = time.time()
    
    def reset(self) -> None:
        """Reset the rate limiter."""
        self.tokens = self.burst_size
        self.last_request_time = 0.0
    
    @property
    def available_tokens(self) -> int:
        """Get the number of available tokens."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        tokens_to_add = time_since_last * self.requests_per_second
        available = min(self.burst_size, self.tokens + tokens_to_add)
        return max(0, int(available))
    
    @property
    def time_until_next(self) -> float:
        """Get time until next request can be made."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        tokens_to_add = time_since_last * self.requests_per_second
        available_tokens = min(self.burst_size, self.tokens + tokens_to_add)
        
        if available_tokens >= 1:
            return 0.0
        
        return self.min_interval - time_since_last


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter implementation.
    
    More sophisticated rate limiting with token bucket algorithm.
    """
    
    def __init__(
        self,
        rate: float,
        capacity: int = 10,
    ):
        """
        Initialize the token bucket rate limiter.
        
        Args:
            rate: Tokens added per second
            capacity: Maximum capacity of the bucket
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    def consume(self, tokens: int = 1) -> float:
        """
        Consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            Time to wait until tokens are available
        """
        now = time.time()
        
        # Refill tokens
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        # If we have enough tokens, consume them
        if self.tokens >= tokens:
            self.tokens -= tokens
            return 0.0
        
        # Otherwise, calculate wait time
        needed = tokens - self.tokens
        wait_time = needed / self.rate
        return wait_time
    
    async def async_consume(self, tokens: int = 1) -> float:
        """
        Consume tokens from the bucket (async version).
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            Time to wait until tokens are available
        """
        async with self.lock:
            return self.consume(tokens)
    
    def wait_and_consume(self, tokens: int = 1) -> None:
        """
        Wait for tokens and consume them.
        
        Args:
            tokens: Number of tokens to consume
        """
        wait_time = self.consume(tokens)
        if wait_time > 0:
            time.sleep(wait_time)
    
    async def async_wait_and_consume(self, tokens: int = 1) -> None:
        """
        Wait for tokens and consume them (async version).
        
        Args:
            tokens: Number of tokens to consume
        """
        wait_time = await self.async_consume(tokens)
        if wait_time > 0:
            await asyncio.sleep(wait_time)


# Create a default rate limiter instance
_default_rate_limiter = RateLimiter(requests_per_second=2.0)


def get_rate_limiter(
    requests_per_second: Optional[float] = None,
    burst_size: Optional[int] = None,
) -> RateLimiter:
    """
    Get a rate limiter instance.
    
    Args:
        requests_per_second: Maximum requests per second
        burst_size: Maximum burst size
        
    Returns:
        RateLimiter instance
    """
    if requests_per_second is None and burst_size is None:
        return _default_rate_limiter
    
    return RateLimiter(
        requests_per_second=requests_per_second or 2.0,
        burst_size=burst_size or 5,
    )


if __name__ == "__main__":
    # Test the rate limiter
    limiter = RateLimiter(requests_per_second=2.0)
    
    print("Testing rate limiter...")
    for i in range(10):
        limiter.wait()
        print(f"Request {i+1} at {time.time()}")
    
    print("Done!")
