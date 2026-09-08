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
Tests for the Open Omniscience caching utilities module.

Tests cover:
- SimpleCache functionality
- Cache decorators
- Thread safety
- TTL expiration
- Size limits and eviction

Author: Ideotion
"""

import sys
import threading
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from utils.cache import SimpleCache, cached


@pytest.fixture
def fake_clock(monkeypatch):
    """Drive cache TTL with a controllable clock instead of real ``time.sleep``.

    Finding OO-D15-006: real-clock waits (6 x ``time.sleep(1.1)`` here) are the
    suite's principal flakiness vector and add ~7 s of pure waiting. The cache
    reads wall time via ``time.time()`` at module scope, so we swap that module's
    ``time`` for a fake whose ``.advance()`` jumps the clock forward deterministically.
    """
    import utils.cache as cache_mod

    class _Clock:
        def __init__(self) -> None:
            self.now = 1_000_000.0

        def time(self) -> float:
            return self.now

        def advance(self, dt: float) -> None:
            self.now += dt

    clock = _Clock()
    monkeypatch.setattr(cache_mod, "time", clock)
    return clock


class TestSimpleCache:
    """Tests for SimpleCache class."""

    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = SimpleCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        cache = SimpleCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiration(self, fake_clock):
        """Test that items expire after TTL."""
        cache = SimpleCache(default_ttl=1)  # 1 second TTL
        cache.set("key1", "value1")

        # Should be available immediately
        assert cache.get("key1") == "value1"

        # Advance past expiration (no real sleep)
        fake_clock.advance(1.1)

        # Should be expired now
        assert cache.get("key1") is None

    def test_custom_ttl(self, fake_clock):
        """Test custom TTL for individual items."""
        cache = SimpleCache(default_ttl=5)
        cache.set("key1", "value1", ttl=1)  # 1 second TTL
        cache.set("key2", "value2")  # Uses default 5 second TTL

        # Advance past key1's TTL but not key2's
        fake_clock.advance(1.1)

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_delete(self):
        """Test deleting items from cache."""
        cache = SimpleCache()
        cache.set("key1", "value1")

        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False

    def test_clear(self):
        """Test clearing the entire cache."""
        cache = SimpleCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.size() == 0

    def test_size(self):
        """Test size tracking."""
        cache = SimpleCache()
        assert cache.size() == 0

        cache.set("key1", "value1")
        assert cache.size() == 1

        cache.set("key2", "value2")
        assert cache.size() == 2

        cache.delete("key1")
        assert cache.size() == 1

    def test_max_size_eviction(self):
        """Test that oldest items are evicted when max size is reached."""
        cache = SimpleCache(max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert cache.size() == 3

        # This should evict the oldest item (key1)
        cache.set("key4", "value4")

        assert cache.size() == 3
        assert cache.get("key1") is None  # Should be evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_contains(self):
        """Test __contains__ method."""
        cache = SimpleCache()
        cache.set("key1", "value1")

        assert "key1" in cache
        assert "key2" not in cache

    def test_stats(self):
        """Test cache statistics."""
        cache = SimpleCache(max_size=10, default_ttl=300)

        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["max_size"] == 10
        assert stats["default_ttl"] == 300
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cleanup_expired(self, fake_clock):
        """Test cleanup of expired items."""
        cache = SimpleCache(default_ttl=1)

        cache.set("key1", "value1")
        cache.set("key2", "value2", ttl=2)

        # Advance past key1's TTL but not key2's
        fake_clock.advance(1.1)

        # Cleanup should remove key1
        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.size() == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"


class TestCacheDecorators:
    """Tests for cache decorators."""

    def test_cached_decorator(self):
        """Test the cached decorator."""
        call_count = 0

        @cached(ttl=2)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * x

        # First call should execute the function
        result1 = expensive_function(5)
        assert result1 == 25
        assert call_count == 1

        # Second call with same arguments should use cache
        result2 = expensive_function(5)
        assert result2 == 25
        assert call_count == 1  # Should not have called the function again

        # Different arguments should call the function
        result3 = expensive_function(3)
        assert result3 == 9
        assert call_count == 2

    def test_cached_decorator_expiration(self, fake_clock):
        """Test that cached decorator respects TTL."""
        call_count = 0

        @cached(ttl=1)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * x

        # First call
        expensive_function(5)
        assert call_count == 1

        # Second call should use cache
        expensive_function(5)
        assert call_count == 1

        # Advance past the cache TTL
        fake_clock.advance(1.1)

        # Third call should execute function again
        expensive_function(5)
        assert call_count == 2


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_access(self):
        """Test that cache is thread-safe."""
        cache = SimpleCache(max_size=1000)
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    cache.set(f"key_{thread_id}_{i}", f"value_{thread_id}_{i}")
                    cache.get(f"key_{thread_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
