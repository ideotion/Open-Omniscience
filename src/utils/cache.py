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
Caching Utilities for Open Omniscience

This module provides simple caching utilities for:
- Function result caching with TTL (Time To Live)
- LRU (Least Recently Used) cache with size limits
- Memory-efficient caching for database queries

Author: Ideotion
"""

import time
import threading
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar
from functools import wraps
import logging

# Configure logging
logger = logging.getLogger(__name__)

T = TypeVar('T')


class SimpleCache:
    """
    A simple thread-safe cache with TTL support.
    
    This cache stores key-value pairs with optional expiration times.
    It's thread-safe and can be used for caching function results or any other data.
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Initialize the cache.
        
        Args:
            max_size: Maximum number of items to store in the cache.
            default_ttl: Default time-to-live in seconds for cached items.
        """
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            The cached value, or None if not found or expired.
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, expiry_time = self._cache[key]
            if time.time() > expiry_time:
                # Item has expired
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set a value in the cache.
        
        Args:
            key: The cache key.
            value: The value to cache.
            ttl: Time-to-live in seconds. Uses default_ttl if not specified.
        """
        if ttl is None:
            ttl = self._default_ttl
        
        expiry_time = time.time() + ttl
        
        with self._lock:
            # If cache is full, remove oldest items (simple FIFO eviction)
            if len(self._cache) >= self._max_size and key not in self._cache:
                self._evict_oldest()
            
            self._cache[key] = (value, expiry_time)
    
    def _evict_oldest(self) -> None:
        """Remove the oldest item from the cache."""
        if not self._cache:
            return
        
        # Find the item with the earliest expiry time
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
        del self._cache[oldest_key]
    
    def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            True if the key was found and deleted, False otherwise.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired items from the cache.
        
        Returns:
            Number of items removed.
        """
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, expiry_time) in self._cache.items()
                if current_time > expiry_time
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def size(self) -> int:
        """Return the number of items in the cache."""
        with self._lock:
            return len(self._cache)
    
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'default_ttl': self._default_ttl,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0.0
            }
    
    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the cache and is not expired."""
        return self.get(key) is not None


class LRUCache:
    """
    A Least Recently Used (LRU) cache with TTL support.
    
    This cache automatically removes the least recently used items when the cache is full.
    It also supports time-to-live for cached items.
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of items to store in the cache.
            default_ttl: Default time-to-live in seconds for cached items.
        """
        self._cache: Dict[str, Tuple[Any, float, float]] = {}  # key: (value, expiry_time, last_access_time)
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            The cached value, or None if not found or expired.
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, expiry_time, _ = self._cache[key]
            if time.time() > expiry_time:
                # Item has expired
                del self._cache[key]
                self._misses += 1
                return None
            
            # Update last access time
            self._cache[key] = (value, expiry_time, time.time())
            self._hits += 1
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set a value in the cache.
        
        Args:
            key: The cache key.
            value: The value to cache.
            ttl: Time-to-live in seconds. Uses default_ttl if not specified.
        """
        if ttl is None:
            ttl = self._default_ttl
        
        expiry_time = time.time() + ttl
        
        with self._lock:
            # If key already exists, just update it
            if key in self._cache:
                self._cache[key] = (value, expiry_time, time.time())
                return
            
            # If cache is full, remove least recently used item
            if len(self._cache) >= self._max_size:
                self._evict_lru()
            
            self._cache[key] = (value, expiry_time, time.time())
    
    def _evict_lru(self) -> None:
        """Remove the least recently used item from the cache."""
        if not self._cache:
            return
        
        # Find the item with the oldest last access time
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k][2])
        del self._cache[lru_key]
    
    def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.
        
        Args:
            key: The cache key.
            
        Returns:
            True if the key was found and deleted, False otherwise.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired items from the cache.
        
        Returns:
            Number of items removed.
        """
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, expiry_time, _) in self._cache.items()
                if current_time > expiry_time
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def size(self) -> int:
        """Return the number of items in the cache."""
        with self._lock:
            return len(self._cache)
    
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'default_ttl': self._default_ttl,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0.0
            }
    
    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the cache and is not expired."""
        return self.get(key) is not None


def cached(ttl: int = 300, cache_instance: Optional[SimpleCache] = None):
    """
    Decorator to cache function results with TTL.
    
    Args:
        ttl: Time-to-live in seconds for cached results.
        cache_instance: Optional cache instance to use. If None, creates a new SimpleCache.
        
    Returns:
        Decorated function with caching.
    """
    if cache_instance is None:
        cache_instance = SimpleCache(default_ttl=ttl)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Create a cache key from function name and arguments
            cache_key = f"{func.__name__}:{hash((args, frozenset(kwargs.items())))}"
            
            # Try to get from cache
            cached_result = cache_instance.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_result
            
            # Call the function and cache the result
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            logger.debug(f"Cache miss for {func.__name__}, result cached")
            return result
        
        return wrapper
    
    return decorator


def lru_cached(max_size: int = 1000, ttl: int = 300, cache_instance: Optional[LRUCache] = None):
    """
    Decorator to cache function results with LRU eviction and TTL.
    
    Args:
        max_size: Maximum number of items to cache.
        ttl: Time-to-live in seconds for cached results.
        cache_instance: Optional cache instance to use. If None, creates a new LRUCache.
        
    Returns:
        Decorated function with caching.
    """
    if cache_instance is None:
        cache_instance = LRUCache(max_size=max_size, default_ttl=ttl)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Create a cache key from function name and arguments
            cache_key = f"{func.__name__}:{hash((args, frozenset(kwargs.items())))}"
            
            # Try to get from cache
            cached_result = cache_instance.get(cache_key)
            if cached_result is not None:
                logger.debug(f"LRU cache hit for {func.__name__}")
                return cached_result
            
            # Call the function and cache the result
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            logger.debug(f"LRU cache miss for {func.__name__}, result cached")
            return result
        
        return wrapper
    
    return decorator


# Global cache instances for common use cases
article_cache = LRUCache(max_size=1000, default_ttl=300)  # Cache for article data
source_cache = LRUCache(max_size=500, default_ttl=600)   # Cache for source data
query_cache = LRUCache(max_size=200, default_ttl=60)    # Cache for search queries


if __name__ == "__main__":
    # Test the caching utilities
    print("Testing SimpleCache...")
    cache = SimpleCache(max_size=10, default_ttl=2)
    
    cache.set("key1", "value1")
    cache.set("key2", "value2", ttl=1)
    
    print(f"key1: {cache.get('key1')}")  # Should return "value1"
    print(f"key2: {cache.get('key2')}")  # Should return "value2"
    print(f"key3: {cache.get('key3')}")  # Should return None
    
    print(f"Stats: {cache.stats()}")
    
    print("\nTesting LRUCache...")
    lru_cache = LRUCache(max_size=3, default_ttl=2)
    
    lru_cache.set("a", 1)
    lru_cache.set("b", 2)
    lru_cache.set("c", 3)
    
    print(f"a: {lru_cache.get('a')}")  # Should return 1
    print(f"b: {lru_cache.get('b')}")  # Should return 2
    print(f"c: {lru_cache.get('c')}")  # Should return 3
    
    # This should evict 'a' (least recently used)
    lru_cache.set("d", 4)
    print(f"a after eviction: {lru_cache.get('a')}")  # Should return None
    
    print(f"Stats: {lru_cache.stats()}")
    
    print("\nTesting cached decorator...")
    
    @cached(ttl=2)
    def expensive_function(x: int) -> int:
        print(f"Computing expensive_function({x})...")
        return x * x
    
    print(f"expensive_function(5) = {expensive_function(5)}")  # Should compute
    print(f"expensive_function(5) = {expensive_function(5)}")  # Should use cache
    print(f"expensive_function(3) = {expensive_function(3)}")  # Should compute
    
    print("\nAll tests completed!")