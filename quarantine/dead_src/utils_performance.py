"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Performance Utilities for Open Omniscience

This module provides performance optimization utilities including:
- Caching mechanisms
- Rate limiting
- Batch processing
- Query optimization helpers
- Performance monitoring

Author: Ideotion
"""

import time
import functools
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from contextlib import contextmanager
import hashlib
import json

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')

# =============================================================================
# Caching Utilities
# =============================================================================

@dataclass
class CacheStats:
    """Statistics for cache performance monitoring."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": f"{self.hit_rate:.2%}"
        }


class LRUCache:
    """
    Thread-safe LRU (Least Recently Used) cache implementation.
    
    This cache automatically evicts the least recently used items when it reaches
    its maximum capacity.
    """
    
    def __init__(self, max_size: int = 1000, ttl: Optional[float] = None):
        """
        Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of items to store in the cache.
            ttl: Time-to-live in seconds for cache entries (None = no expiration).
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = Lock()
        self._stats = CacheStats(max_size=max_size)
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get an item from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            The cached value, or None if not found or expired.
        """
        with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                return None
            
            value, timestamp = self._cache[key]
            
            # Check TTL if configured
            if self.ttl and (time.time() - timestamp) > self.ttl:
                del self._cache[key]
                self._stats.evictions += 1
                self._stats.misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._stats.hits += 1
            return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set an item in the cache.
        
        Args:
            key: The cache key.
            value: The value to cache.
        """
        with self._lock:
            # If key exists, remove it first
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self.max_size:
                # Evict least recently used
                self._cache.popitem(last=False)
                self._stats.evictions += 1
            
            self._cache[key] = (value, time.time())
            self._stats.size = len(self._cache)
    
    def delete(self, key: str) -> bool:
        """
        Delete an item from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            True if the item was deleted, False if not found.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.size = len(self._cache)
                return True
            return False
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._cache.clear()
            self._stats.size = 0
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            self._stats.size = len(self._cache)
            return self._stats
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self._lock:
            if key not in self._cache:
                return False
            
            # Check TTL if configured
            if self.ttl:
                _, timestamp = self._cache[key]
                if (time.time() - timestamp) > self.ttl:
                    del self._cache[key]
                    self._stats.evictions += 1
                    return False
            
            return True


# Global cache instances
url_cache = LRUCache(max_size=10000, ttl=3600)  # 1 hour TTL for URLs
content_cache = LRUCache(max_size=5000, ttl=1800)  # 30 minutes TTL for content
query_cache = LRUCache(max_size=1000, ttl=600)  # 10 minutes TTL for queries


# =============================================================================
# Rate Limiting Utilities
# =============================================================================

@dataclass
class RateLimiter:
    """
    Token bucket rate limiter for controlling request rates.
    
    This implements the token bucket algorithm for rate limiting.
    """
    tokens: int = 10  # Maximum number of tokens (bucket capacity)
    fill_rate: float = 1.0  # Tokens added per second
    last_check: float = field(default_factory=time.time)
    current_tokens: int = field(default=10)
    
    def acquire(self, tokens_needed: int = 1) -> bool:
        """
        Try to acquire tokens for a request.
        
        Args:
            tokens_needed: Number of tokens needed.
            
        Returns:
            True if tokens were acquired, False if rate limited.
        """
        now = time.time()
        elapsed = now - self.last_check
        self.last_check = now
        
        # Add tokens based on fill rate
        self.current_tokens = min(self.tokens, self.current_tokens + elapsed * self.fill_rate)
        
        if self.current_tokens >= tokens_needed:
            self.current_tokens -= tokens_needed
            return True
        
        return False
    
    def wait(self, tokens_needed: int = 1) -> float:
        """
        Wait until tokens are available.
        
        Args:
            tokens_needed: Number of tokens needed.
            
        Returns:
            Time waited in seconds.
        """
        start_time = time.time()
        
        while not self.acquire(tokens_needed):
            # Calculate time needed to get required tokens
            tokens_needed_total = tokens_needed - self.current_tokens
            wait_time = tokens_needed_total / self.fill_rate
            time.sleep(max(0, wait_time))
        
        return time.time() - start_time
    
    def reset(self) -> None:
        """Reset the rate limiter."""
        self.current_tokens = self.tokens
        self.last_check = time.time()


# Global rate limiters
scraper_rate_limiter = RateLimiter(tokens=20, fill_rate=2.0)  # 20 requests, 2 per second
api_rate_limiter = RateLimiter(tokens=100, fill_rate=10.0)  # 100 requests, 10 per second


# =============================================================================
# Batch Processing Utilities
# =============================================================================

def batch_process(
    items: List[T],
    processor: Callable[[T], R],
    batch_size: int = 100,
    max_workers: int = 4,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> List[R]:
    """
    Process items in batches with optional parallelism.
    
    Args:
        items: List of items to process.
        processor: Function to process each item.
        batch_size: Number of items per batch.
        max_workers: Maximum number of parallel workers.
        progress_callback: Optional callback for progress updates.
        
    Returns:
        List of processed results.
    """
    import concurrent.futures
    
    results: List[R] = []
    total_items = len(items)
    
    def process_batch(batch: List[T]) -> List[R]:
        """Process a single batch."""
        return [processor(item) for item in batch]
    
    # Process in batches
    for i in range(0, total_items, batch_size):
        batch = items[i:i + batch_size]
        
        if max_workers > 1:
            # Use thread pool for parallel processing
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                batch_results = list(executor.map(processor, batch))
        else:
            # Sequential processing
            batch_results = process_batch(batch)
        
        results.extend(batch_results)
        
        # Update progress
        if progress_callback:
            progress_callback(i + len(batch), total_items)
    
    return results


@contextmanager
def performance_timer(name: str = "Operation"):
    """
    Context manager for timing operations.
    
    Args:
        name: Name of the operation being timed.
        
    Yields:
        None
    
    Example:
        with performance_timer("Database query"):
            result = session.query(Article).all()
    """
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.info(f"{name} completed in {elapsed:.4f} seconds")


# =============================================================================
# Query Optimization Utilities
# =============================================================================

def paginate_query(
    query: Any,
    page: int = 1,
    per_page: int = 50,
    max_pages: Optional[int] = None
) -> Tuple[List[Any], int, int]:
    """
    Paginate a SQLAlchemy query efficiently.
    
    Args:
        query: SQLAlchemy query object.
        page: Page number (1-based).
        per_page: Number of items per page.
        max_pages: Maximum number of pages to return.
        
    Returns:
        Tuple of (items, total_pages, total_count).
    """
    # Get total count (using count() which is optimized in most databases)
    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page
    
    if max_pages and total_pages > max_pages:
        total_pages = max_pages
    
    # Ensure page is within bounds
    page = max(1, min(page, total_pages))
    
    # Execute paginated query
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    
    return items, total_pages, total_count


def chunked_query(
    query: Any,
    chunk_size: int = 1000,
    process_func: Callable[[List[Any]], None] = None
) -> None:
    """
    Process a large query in chunks to avoid memory issues.
    
    Args:
        query: SQLAlchemy query object.
        chunk_size: Number of items per chunk.
        process_func: Function to process each chunk.
    """
    offset = 0
    
    while True:
        # Get a chunk of results
        chunk = query.offset(offset).limit(chunk_size).all()
        
        if not chunk:
            break
        
        # Process the chunk
        process_func(chunk)
        
        # Move to next chunk
        offset += chunk_size


# =============================================================================
# String and Text Processing Utilities
# =============================================================================

def generate_cache_key(*args: Any, **kwargs: Any) -> str:
    """
    Generate a consistent cache key from arbitrary arguments.
    
    Args:
        *args: Positional arguments.
        **kwargs: Keyword arguments.
        
    Returns:
        A SHA-256 hash string.
    """
    # Convert all arguments to a stable string representation
    key_data = {
        "args": args,
        "kwargs": sorted(kwargs.items())
    }
    
    # Use JSON for consistent serialization
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    
    # Generate SHA-256 hash
    return hashlib.sha256(key_string.encode()).hexdigest()


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length.
    
    Args:
        text: The text to truncate.
        max_length: Maximum length of the result.
        suffix: Suffix to add if text is truncated.
        
    Returns:
        The truncated text.
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def normalize_for_search(text: str) -> str:
    """
    Normalize text for search operations.
    
    Args:
        text: The text to normalize.
        
    Returns:
        Normalized text.
    """
    import re
    import unicodedata
    
    # Normalize unicode
    text = unicodedata.normalize('NFKD', text)
    
    # Remove diacritics
    text = ''.join(c for c in text if not unicodedata.combining(c))
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove special characters and extra whitespace
    text = re.sub(r'[^\w\s-]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


# =============================================================================
# Decorators
# =============================================================================

def cached(ttl: Optional[float] = None, max_size: int = 1000):
    """
    Decorator to cache function results.
    
    Args:
        ttl: Time-to-live in seconds for cache entries.
        max_size: Maximum number of items to cache.
        
    Returns:
        Decorated function with caching.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache = LRUCache(max_size=max_size, ttl=ttl)
        
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Generate cache key from function arguments
            cache_key = generate_cache_key(func.__name__, args, kwargs)
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            
            return result
        
        return wrapper
    
    return decorator


def rate_limited(max_calls: int = 10, period: float = 1.0):
    """
    Decorator to rate limit function calls.
    
    Args:
        max_calls: Maximum number of calls per period.
        period: Time period in seconds.
        
    Returns:
        Decorated function with rate limiting.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        rate_limiter = RateLimiter(tokens=max_calls, fill_rate=max_calls / period)
        
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if not rate_limiter.acquire():
                wait_time = rate_limiter.wait()
                logger.warning(f"Rate limited {func.__name__}, waited {wait_time:.2f}s")
            
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator to retry function on failure with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier for exponential backoff.
        
    Returns:
        Decorated function with retry logic.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}. Retrying in {wait_time:.2f}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed for {func.__name__}: {e}")
            
            raise last_exception
        
        return wrapper
    
    return decorator


def timed(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to log function execution time.
    
    Args:
        func: The function to decorate.
        
    Returns:
        Decorated function that logs execution time.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__name__} executed in {elapsed:.4f} seconds")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.4f} seconds: {e}")
            raise
    
    return wrapper


# =============================================================================
# Performance Monitoring
# =============================================================================

@dataclass
class PerformanceMetrics:
    """Performance metrics for monitoring."""
    function_name: str
    call_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    error_count: int = 0
    
    @property
    def avg_time(self) -> float:
        """Calculate average execution time."""
        return self.total_time / self.call_count if self.call_count > 0 else 0.0
    
    def record(self, execution_time: float, success: bool = True) -> None:
        """
        Record a function execution.
        
        Args:
            execution_time: Time taken for execution in seconds.
            success: Whether the execution was successful.
        """
        self.call_count += 1
        self.total_time += execution_time
        self.min_time = min(self.min_time, execution_time)
        self.max_time = max(self.max_time, execution_time)
        
        if not success:
            self.error_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "function_name": self.function_name,
            "call_count": self.call_count,
            "total_time": f"{self.total_time:.4f}s",
            "avg_time": f"{self.avg_time:.4f}s",
            "min_time": f"{self.min_time:.4f}s" if self.min_time != float('inf') else "N/A",
            "max_time": f"{self.max_time:.4f}s",
            "error_count": self.error_count,
            "error_rate": f"{self.error_count / self.call_count:.2%}" if self.call_count > 0 else "0%"
        }


class PerformanceMonitor:
    """Monitor performance of multiple functions."""
    
    def __init__(self) -> None:
        self._metrics: Dict[str, PerformanceMetrics] = {}
        self._lock = Lock()
    
    def get_metrics(self, function_name: str) -> PerformanceMetrics:
        """Get or create metrics for a function."""
        with self._lock:
            if function_name not in self._metrics:
                self._metrics[function_name] = PerformanceMetrics(function_name=function_name)
            return self._metrics[function_name]
    
    def record(self, function_name: str, execution_time: float, success: bool = True) -> None:
        """Record a function execution."""
        metrics = self.get_metrics(function_name)
        metrics.record(execution_time, success)
    
    def get_all_metrics(self) -> List[Dict[str, Any]]:
        """Get all metrics as a list of dictionaries."""
        with self._lock:
            return [metrics.to_dict() for metrics in self._metrics.values()]
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()


# Global performance monitor
performance_monitor = PerformanceMonitor()


def monitored(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to monitor function performance.
    
    Args:
        func: The function to monitor.
        
    Returns:
        Decorated function that records performance metrics.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        start_time = time.time()
        success = True
        
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            raise
        finally:
            execution_time = time.time() - start_time
            performance_monitor.record(func.__name__, execution_time, success)
    
    return wrapper


__all__ = [
    # Caching
    'LRUCache', 'CacheStats',
    'url_cache', 'content_cache', 'query_cache',
    
    # Rate Limiting
    'RateLimiter',
    'scraper_rate_limiter', 'api_rate_limiter',
    
    # Batch Processing
    'batch_process',
    
    # Timing
    'performance_timer',
    
    # Query Optimization
    'paginate_query', 'chunked_query',
    
    # String Processing
    'generate_cache_key', 'truncate_text', 'normalize_for_search',
    
    # Decorators
    'cached', 'rate_limited', 'retry_on_failure', 'timed', 'monitored',
    
    # Monitoring
    'PerformanceMetrics', 'PerformanceMonitor', 'performance_monitor',
]
