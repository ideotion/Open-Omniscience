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
Pillar 4: Real-Time Monitoring & Alerting System - Cache Manager

Caching utilities for performance optimization.
"""

import time
import json
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Tuple, TypeVar
from enum import Enum
import logging
import os
import sqlite3
from pathlib import Path


T = TypeVar('T')


class CacheType(Enum):
    MEMORY = "memory"
    DISK = "disk"
    DATABASE = "database"


class EvictionPolicy(Enum):
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In First Out
    TIME_BASED = "time_based"  # Time-based expiration


@dataclass
class CacheConfig:
    """Configuration for a cache."""
    cache_type: CacheType = CacheType.MEMORY
    max_size: int = 1000
    ttl: float = 3600.0  # Time to live in seconds
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    cache_dir: str = ".cache"  # For disk cache
    db_path: str = "cache.db"  # For database cache


@dataclass
class CacheEntry:
    """A cache entry with value and metadata."""
    key: str
    value: Any
    created_at: float
    accessed_at: float
    expires_at: float
    access_count: int = 0
    size: int = 0

    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() > self.expires_at


class BaseCache:
    """Base class for cache implementations."""

    def __init__(self, config: CacheConfig):
        """
        Initialize the cache.

        Args:
            config: Cache configuration.
        """
        self.config = config
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    def get(self, key: str) -> Optional[T]:
        """Get a value from the cache."""
        raise NotImplementedError

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Set a value in the cache."""
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        raise NotImplementedError

    def clear(self) -> None:
        """Clear all entries from the cache."""
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        raise NotImplementedError

    def size(self) -> int:
        """Get the number of entries in the cache."""
        raise NotImplementedError

    def cleanup(self) -> int:
        """Clean up expired entries. Returns number of entries removed."""
        raise NotImplementedError


class MemoryCache(BaseCache):
    """In-memory cache implementation with LRU eviction."""

    def __init__(self, config: CacheConfig):
        """
        Initialize the memory cache.

        Args:
            config: Cache configuration.
        """
        super().__init__(config)
        self.cache: Dict[str, CacheEntry] = {}
        self.access_order: List[str] = []  # For LRU eviction

    def _evict(self) -> None:
        """Evict entries according to the eviction policy."""
        if len(self.cache) <= self.config.max_size:
            return

        if self.config.eviction_policy == EvictionPolicy.LRU:
            # Remove least recently used
            if self.access_order:
                oldest_key = self.access_order.pop(0)
                if oldest_key in self.cache:
                    del self.cache[oldest_key]

        elif self.config.eviction_policy == EvictionPolicy.FIFO:
            # Remove oldest entry
            if self.access_order:
                oldest_key = self.access_order.pop(0)
                if oldest_key in self.cache:
                    del self.cache[oldest_key]

        # For simplicity, we don't implement LFU here

    def get(self, key: str) -> Optional[T]:
        """Get a value from the cache."""
        entry = self.cache.get(key)
        if not entry:
            return None

        if entry.is_expired():
            self.delete(key)
            return None

        # Update access metadata
        entry.accessed_at = time.time()
        entry.access_count += 1

        # Update access order for LRU
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

        return entry.value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Set a value in the cache."""
        # Evict if necessary
        self._evict()

        # Calculate expiration
        if ttl is None:
            ttl = self.config.ttl
        expires_at = time.time() + ttl

        # Create entry
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            accessed_at=time.time(),
            expires_at=expires_at,
            access_count=0,
        )

        self.cache[key] = entry

        # Update access order
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

    def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        if key in self.cache:
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)
            return True
        return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        self.cache.clear()
        self.access_order.clear()

    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        entry = self.cache.get(key)
        if not entry:
            return False
        return not entry.is_expired()

    def size(self) -> int:
        """Get the number of entries in the cache."""
        return len(self.cache)

    def cleanup(self) -> int:
        """Clean up expired entries."""
        expired_keys = [key for key, entry in self.cache.items() if entry.is_expired()]
        for key in expired_keys:
            self.delete(key)
        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size(),
            "max_size": self.config.max_size,
            "ttl": self.config.ttl,
            "eviction_policy": self.config.eviction_policy.value,
        }


class DiskCache(BaseCache):
    """Disk-based cache implementation."""

    def __init__(self, config: CacheConfig):
        """
        Initialize the disk cache.

        Args:
            config: Cache configuration.
        """
        super().__init__(config)
        self.cache_dir = Path(config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        # Create a safe filename from the key
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"

    def _read_entry(self, path: Path) -> Optional[CacheEntry]:
        """Read a cache entry from disk."""
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return CacheEntry(
                    key=data["key"],
                    value=data["value"],
                    created_at=data["created_at"],
                    accessed_at=data["accessed_at"],
                    expires_at=data["expires_at"],
                    access_count=data.get("access_count", 0),
                )
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def _write_entry(self, path: Path, entry: CacheEntry) -> bool:
        """Write a cache entry to disk."""
        try:
            with open(path, 'w') as f:
                json.dump({
                    "key": entry.key,
                    "value": entry.value,
                    "created_at": entry.created_at,
                    "accessed_at": entry.accessed_at,
                    "expires_at": entry.expires_at,
                    "access_count": entry.access_count,
                }, f)
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[T]:
        """Get a value from the cache."""
        path = self._get_path(key)
        entry = self._read_entry(path)

        if not entry:
            return None

        if entry.is_expired():
            self.delete(key)
            return None

        # Update access metadata
        entry.accessed_at = time.time()
        entry.access_count += 1
        self._write_entry(path, entry)

        return entry.value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Set a value in the cache."""
        # Calculate expiration
        if ttl is None:
            ttl = self.config.ttl
        expires_at = time.time() + ttl

        # Create entry
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            accessed_at=time.time(),
            expires_at=expires_at,
            access_count=0,
        )

        # Write to disk
        path = self._get_path(key)
        self._write_entry(path, entry)

        # Clean up old entries if we're over max_size
        if self.size() > self.config.max_size:
            self._cleanup_oldest()

    def _cleanup_oldest(self) -> None:
        """Remove the oldest entries to stay under max_size."""
        entries = []
        for path in self.cache_dir.glob("*.cache"):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    entries.append((path, data["created_at"]))
            except (json.JSONDecodeError, KeyError):
                path.unlink()  # Remove corrupted files

        # Sort by creation time (oldest first)
        entries.sort(key=lambda x: x[1])

        # Remove oldest entries
        while len(entries) > self.config.max_size:
            oldest_path, _ = entries.pop(0)
            oldest_path.unlink()

    def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        path = self._get_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        for path in self.cache_dir.glob("*.cache"):
            path.unlink()

    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        path = self._get_path(key)
        if not path.exists():
            return False

        entry = self._read_entry(path)
        if not entry:
            return False

        return not entry.is_expired()

    def size(self) -> int:
        """Get the number of entries in the cache."""
        return sum(1 for _ in self.cache_dir.glob("*.cache"))

    def cleanup(self) -> int:
        """Clean up expired entries."""
        cleaned = 0
        for path in self.cache_dir.glob("*.cache"):
            entry = self._read_entry(path)
            if entry and entry.is_expired():
                path.unlink()
                cleaned += 1
        return cleaned

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size(),
            "max_size": self.config.max_size,
            "ttl": self.config.ttl,
            "cache_dir": str(self.cache_dir),
            "cache_type": self.config.cache_type.value,
        }


class DatabaseCache(BaseCache):
    """SQLite-based cache implementation."""

    def __init__(self, config: CacheConfig):
        """
        Initialize the database cache.

        Args:
            config: Cache configuration.
        """
        super().__init__(config)
        self.db_path = config.db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON cache(expires_at)")
            conn.commit()

    def _get_entry(self, key: str) -> Optional[CacheEntry]:
        """Get a cache entry from the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT key, value, created_at, accessed_at, expires_at, access_count FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return CacheEntry(
                key=row[0],
                value=json.loads(row[1]),
                created_at=row[2],
                accessed_at=row[3],
                expires_at=row[4],
                access_count=row[5],
            )

    def _set_entry(self, entry: CacheEntry) -> bool:
        """Set a cache entry in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cache (key, value, created_at, accessed_at, expires_at, access_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entry.key,
                    json.dumps(entry.value),
                    entry.created_at,
                    entry.accessed_at,
                    entry.expires_at,
                    entry.access_count,
                ))
                conn.commit()
            return True
        except Exception:
            return False

    def _delete_entry(self, key: str) -> bool:
        """Delete a cache entry from the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def get(self, key: str) -> Optional[T]:
        """Get a value from the cache."""
        entry = self._get_entry(key)

        if not entry:
            return None

        if entry.is_expired():
            self.delete(key)
            return None

        # Update access metadata
        entry.accessed_at = time.time()
        entry.access_count += 1
        self._set_entry(entry)

        return entry.value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Set a value in the cache."""
        # Calculate expiration
        if ttl is None:
            ttl = self.config.ttl
        expires_at = time.time() + ttl

        # Create entry
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            accessed_at=time.time(),
            expires_at=expires_at,
            access_count=0,
        )

        self._set_entry(entry)

        # Clean up if we're over max_size
        if self.size() > self.config.max_size:
            self._cleanup_oldest()

    def _cleanup_oldest(self) -> None:
        """Remove the oldest entries to stay under max_size."""
        with sqlite3.connect(self.db_path) as conn:
            # Delete oldest entries
            conn.execute("""
                DELETE FROM cache
                WHERE key IN (
                    SELECT key FROM cache
                    ORDER BY created_at ASC
                    LIMIT ?
                )
            """, (max(0, self.size() - self.config.max_size),))
            conn.commit()

    def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        return self._delete_entry(key)

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache")
            conn.commit()

    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        entry = self._get_entry(key)
        if not entry:
            return False
        return not entry.is_expired()

    def size(self) -> int:
        """Get the number of entries in the cache."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            return cursor.fetchone()[0]

    def cleanup(self) -> int:
        """Clean up expired entries."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            size = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM cache WHERE expires_at < ?", (time.time(),))
            expired = cursor.fetchone()[0]

        return {
            "size": size,
            "max_size": self.config.max_size,
            "ttl": self.config.ttl,
            "db_path": self.db_path,
            "cache_type": self.config.cache_type.value,
            "expired_entries": expired,
        }


class CacheManager:
    """
    Manager for multiple caches with different configurations.
    """

    def __init__(self):
        """Initialize the cache manager."""
        self.caches: Dict[str, BaseCache] = {}
        self.logger = logging.getLogger("CacheManager")

    def create_cache(self, cache_id: str, config: CacheConfig) -> BaseCache:
        """
        Create a new cache.

        Args:
            cache_id: Unique identifier for the cache.
            config: Cache configuration.

        Returns:
            The created cache.
        """
        if config.cache_type == CacheType.MEMORY:
            cache = MemoryCache(config)
        elif config.cache_type == CacheType.DISK:
            cache = DiskCache(config)
        elif config.cache_type == CacheType.DATABASE:
            cache = DatabaseCache(config)
        else:
            raise ValueError(f"Unknown cache type: {config.cache_type}")

        self.caches[cache_id] = cache
        self.logger.info(f"Created cache: {cache_id} ({config.cache_type.value})")
        return cache

    def get_cache(self, cache_id: str) -> Optional[BaseCache]:
        """Get a cache by ID."""
        return self.caches.get(cache_id)

    def delete_cache(self, cache_id: str) -> bool:
        """Delete a cache."""
        if cache_id in self.caches:
            self.caches[cache_id].clear()
            del self.caches[cache_id]
            self.logger.info(f"Deleted cache: {cache_id}")
            return True
        return False

    def get_or_create(self, cache_id: str, config: CacheConfig) -> BaseCache:
        """
        Get a cache by ID, or create it if it doesn't exist.

        Args:
            cache_id: Unique identifier for the cache.
            config: Cache configuration (used if cache doesn't exist).

        Returns:
            The cache.
        """
        if cache_id not in self.caches:
            return self.create_cache(cache_id, config)
        return self.caches[cache_id]

    def clear_all(self) -> None:
        """Clear all caches."""
        for cache in self.caches.values():
            cache.clear()
        self.logger.info("Cleared all caches")

    def cleanup_all(self) -> Dict[str, int]:
        """
        Clean up all caches.

        Returns:
            Dictionary mapping cache IDs to number of entries cleaned.
        """
        results = {}
        for cache_id, cache in self.caches.items():
            results[cache_id] = cache.cleanup()
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get cache manager statistics."""
        return {
            "total_caches": len(self.caches),
            "caches": {
                cache_id: cache.get_stats()
                for cache_id, cache in self.caches.items()
            },
        }


# Convenience function for caching decorators
def cached(
    cache_id: str = "default",
    ttl: Optional[float] = None,
    key_func: Optional[Callable[..., str]] = None,
) -> Callable:
    """
    Decorator for caching function results.

    Args:
        cache_id: Cache ID to use.
        ttl: Time to live for cache entries.
        key_func: Function to generate cache keys from function arguments.

    Returns:
        Decorator function.
    """
    # Default cache manager (can be replaced with a custom one)
    cache_manager = CacheManager()

    def decorator(func: Callable) -> Callable:
        def get_key(*args, **kwargs) -> str:
            if key_func:
                return key_func(*args, **kwargs)
            # Default: use function name and arguments
            key_str = f"{func.__module__}.{func.__qualname__}:{args}:{frozenset(kwargs.items())}"
            return hashlib.sha256(key_str.encode()).hexdigest()

        def wrapper(*args, **kwargs) -> T:
            cache = cache_manager.get_or_create(
                cache_id,
                CacheConfig(
                    cache_type=CacheType.MEMORY,
                    ttl=ttl if ttl is not None else 3600.0,
                )
            )

            key = get_key(*args, **kwargs)
            cached_result = cache.get(key)

            if cached_result is not None:
                return cached_result

            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result

        return wrapper

    return decorator
