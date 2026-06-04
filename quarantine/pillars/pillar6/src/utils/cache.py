"""
Cache Utility

Provides caching functionality for web scraping and data processing.
"""

import os
import json
import pickle
import hashlib
import time
from typing import Any, Optional, Dict, Union
from pathlib import Path
import logging

# Configure logging
logger = logging.getLogger(__name__)


class SimpleCache:
    """
    Simple in-memory cache with TTL (Time To Live) support.
    
    Provides basic caching functionality for storing and retrieving data
    with optional expiration.
    """
    
    def __init__(self, default_ttl: int = 3600, max_size: int = 1000):
        """
        Initialize the cache.
        
        Args:
            default_ttl: Default time to live in seconds
            max_size: Maximum number of items in cache
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Set a value in the cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (overrides default)
        """
        # Clean up if cache is full
        if len(self._cache) >= self.max_size:
            self._cleanup_expired()
            if len(self._cache) >= self.max_size:
                self._evict_oldest()
        
        # Store the value with metadata
        self._cache[key] = {
            "value": value,
            "expires": time.time() + (ttl or self.default_ttl),
            "created": time.time(),
        }
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found or expired
        """
        if key not in self._cache:
            self._misses += 1
            return None
        
        item = self._cache[key]
        
        # Check if expired
        if time.time() > item["expires"]:
            del self._cache[key]
            self._misses += 1
            return None
        
        self._hits += 1
        return item["value"]
    
    def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was found and deleted, False otherwise
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the cache and is not expired.
        
        Args:
            key: Cache key
            
        Returns:
            True if key exists and is not expired, False otherwise
        """
        if key not in self._cache:
            return False
        
        item = self._cache[key]
        
        if time.time() > item["expires"]:
            del self._cache[key]
            return False
        
        return True
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def _cleanup_expired(self) -> int:
        """
        Remove expired items from the cache.
        
        Returns:
            Number of items removed
        """
        current_time = time.time()
        expired_keys = [
            key for key, item in self._cache.items()
            if current_time > item["expires"]
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        return len(expired_keys)
    
    def _evict_oldest(self) -> None:
        """Evict the oldest item from the cache."""
        if not self._cache:
            return
        
        oldest_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k]["created"]
        )
        del self._cache[oldest_key]
    
    def cleanup(self) -> int:
        """
        Clean up expired items and return count.
        
        Returns:
            Number of items removed
        """
        return self._cleanup_expired()
    
    @property
    def size(self) -> int:
        """Get the current number of items in the cache."""
        return len(self._cache)
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size,
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0,
        }
    
    def get_all_keys(self) -> list:
        """Get all keys in the cache."""
        return list(self._cache.keys())


class FileCache:
    """
    File-based cache for persistent storage.
    
    Stores cached data in files on disk with TTL support.
    """
    
    def __init__(
        self,
        cache_dir: str = ".cache",
        default_ttl: int = 86400,  # 24 hours
        use_json: bool = True,
    ):
        """
        Initialize the file cache.
        
        Args:
            cache_dir: Directory to store cache files
            default_ttl: Default time to live in seconds
            use_json: Whether to use JSON (True) or pickle (False) for serialization
        """
        self.cache_dir = Path(cache_dir)
        self.default_ttl = default_ttl
        self.use_json = use_json
        self._memory_cache = SimpleCache(default_ttl=default_ttl)
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        # Create a safe filename from the key
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"
    
    def _serialize(self, value: Any) -> str:
        """Serialize a value for storage."""
        if self.use_json:
            return json.dumps(value)
        else:
            return pickle.dumps(value)
    
    def _deserialize(self, data: Union[str, bytes]) -> Any:
        """Deserialize a value from storage."""
        if self.use_json:
            return json.loads(data)
        else:
            return pickle.loads(data)
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        use_memory_cache: bool = True,
    ) -> None:
        """
        Set a value in the cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (overrides default)
            use_memory_cache: Whether to also cache in memory
        """
        # Store in memory cache
        if use_memory_cache:
            self._memory_cache.set(key, value, ttl)
        
        # Store in file
        cache_path = self._get_cache_path(key)
        
        try:
            data = self._serialize(value)
            
            # Create metadata
            metadata = {
                "expires": time.time() + (ttl or self.default_ttl),
                "created": time.time(),
            }
            
            # Write data and metadata to file
            with open(cache_path, "wb") as f:
                if self.use_json:
                    # For JSON, we need to store metadata separately
                    cache_data = {
                        "metadata": metadata,
                        "data": value,
                    }
                    f.write(json.dumps(cache_data).encode())
                else:
                    # For pickle, we can store the whole object
                    cache_data = {
                        "metadata": metadata,
                        "data": data,
                    }
                    f.write(pickle.dumps(cache_data))
        
        except Exception as e:
            logger.error(f"Failed to write cache file for {key}: {e}")
    
    def get(self, key: str, use_memory_cache: bool = True) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: Cache key
            use_memory_cache: Whether to check memory cache first
            
        Returns:
            Cached value or None if not found or expired
        """
        # Check memory cache first
        if use_memory_cache:
            value = self._memory_cache.get(key)
            if value is not None:
                return value
        
        # Check file cache
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "rb") as f:
                if self.use_json:
                    cache_data = json.loads(f.read().decode())
                else:
                    cache_data = pickle.loads(f.read())
            
            # Check expiration
            if time.time() > cache_data["metadata"]["expires"]:
                cache_path.unlink()  # Delete expired file
                return None
            
            # Update memory cache
            if use_memory_cache:
                self._memory_cache.set(
                    key,
                    cache_data["data"],
                    ttl=int(cache_data["metadata"]["expires"] - time.time())
                )
            
            return cache_data["data"]
        
        except Exception as e:
            logger.error(f"Failed to read cache file for {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was found and deleted, False otherwise
        """
        # Delete from memory cache
        self._memory_cache.delete(key)
        
        # Delete from file
        cache_path = self._get_cache_path(key)
        
        if cache_path.exists():
            cache_path.unlink()
            return True
        
        return False
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        self._memory_cache.clear()
        
        # Delete all cache files
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
            except Exception as e:
                logger.error(f"Failed to delete cache file {cache_file}: {e}")
    
    def cleanup(self) -> int:
        """
        Clean up expired items and return count.
        
        Returns:
            Number of items removed
        """
        count = self._memory_cache.cleanup()
        
        # Clean up expired files
        file_count = 0
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                with open(cache_file, "rb") as f:
                    if self.use_json:
                        cache_data = json.loads(f.read().decode())
                    else:
                        cache_data = pickle.loads(f.read())
                
                if time.time() > cache_data["metadata"]["expires"]:
                    cache_file.unlink()
                    file_count += 1
            except Exception as e:
                logger.error(f"Failed to check cache file {cache_file}: {e}")
        
        return count + file_count
    
    @property
    def size(self) -> int:
        """Get the current number of items in the cache."""
        return self._memory_cache.size + len(list(self.cache_dir.glob("*.cache")))


class RobotsTxtCache:
    """
    Specialized cache for robots.txt data.
    
    Stores robots.txt rules with domain-specific caching.
    """
    
    def __init__(self, default_ttl: int = 86400):  # 24 hours
        """
        Initialize the robots.txt cache.
        
        Args:
            default_ttl: Default time to live in seconds
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def set(
        self,
        domain: str,
        rules: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> None:
        """
        Set robots.txt rules for a domain.
        
        Args:
            domain: Domain name
            rules: Parsed robots.txt rules
            ttl: Time to live in seconds (overrides default)
        """
        self._cache[domain] = {
            "rules": rules,
            "expires": time.time() + (ttl or self.default_ttl),
            "created": time.time(),
        }
    
    def get(self, domain: str) -> Optional[Dict[str, Any]]:
        """
        Get robots.txt rules for a domain.
        
        Args:
            domain: Domain name
            
        Returns:
            Parsed robots.txt rules or None if not found or expired
        """
        if domain not in self._cache:
            return None
        
        item = self._cache[domain]
        
        # Check if expired
        if time.time() > item["expires"]:
            del self._cache[domain]
            return None
        
        return item["rules"]
    
    def delete(self, domain: str) -> bool:
        """
        Delete robots.txt rules for a domain.
        
        Args:
            domain: Domain name
            
        Returns:
            True if domain was found and deleted, False otherwise
        """
        if domain in self._cache:
            del self._cache[domain]
            return True
        return False
    
    def clear(self) -> None:
        """Clear all robots.txt rules from the cache."""
        self._cache.clear()
    
    def cleanup(self) -> int:
        """
        Clean up expired items and return count.
        
        Returns:
            Number of items removed
        """
        current_time = time.time()
        expired_domains = [
            domain for domain, item in self._cache.items()
            if current_time > item["expires"]
        ]
        
        for domain in expired_domains:
            del self._cache[domain]
        
        return len(expired_domains)
    
    @property
    def size(self) -> int:
        """Get the current number of domains in the cache."""
        return len(self._cache)


# Create default cache instances
_default_cache = SimpleCache()
_default_file_cache = FileCache()
_default_robots_cache = RobotsTxtCache()


def get_cache(
    cache_type: str = "simple",
    **kwargs: Any,
) -> Union[SimpleCache, FileCache, RobotsTxtCache]:
    """
    Get a cache instance.
    
    Args:
        cache_type: Type of cache ("simple", "file", "robots")
        **kwargs: Additional arguments for cache initialization
        
    Returns:
        Cache instance
    """
    if cache_type == "simple":
        return SimpleCache(**kwargs)
    elif cache_type == "file":
        return FileCache(**kwargs)
    elif cache_type == "robots":
        return RobotsTxtCache(**kwargs)
    else:
        raise ValueError(f"Unknown cache type: {cache_type}")


if __name__ == "__main__":
    # Test the cache functionality
    print("Testing SimpleCache...")
    cache = SimpleCache(default_ttl=5)
    
    # Test set and get
    cache.set("test_key", "test_value")
    value = cache.get("test_key")
    print(f"Got value: {value}")
    
    # Test TTL
    import time
    cache.set("short_ttl", "short_value", ttl=1)
    time.sleep(2)
    value = cache.get("short_ttl")
    print(f"Got expired value: {value}")
    
    # Test stats
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.get("key1")
    cache.get("key1")
    cache.get("nonexistent")
    
    print(f"Cache stats: {cache.stats}")
    
    print("\nTesting FileCache...")
    file_cache = FileCache(cache_dir=".test_cache", default_ttl=5)
    file_cache.set("file_key", {"data": "file_value"})
    value = file_cache.get("file_key")
    print(f"Got file value: {value}")
    
    # Cleanup
    file_cache.clear()
    import shutil
    shutil.rmtree(".test_cache", ignore_errors=True)
    
    print("\nDone!")
