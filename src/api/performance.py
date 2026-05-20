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
API Performance Optimization for Open Omniscience

This module provides comprehensive API performance optimizations including:
- Async FastAPI endpoints
- Response caching (Redis + in-memory)
- Pagination optimization
- Rate limiting and throttling
- Request batching
- Response compression
- Performance monitoring and metrics
- Health checks and status endpoints

Author: Ideotion
"""

import asyncio
import gzip
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
import threading

from fastapi import (
    FastAPI, 
    Request, 
    Response, 
    HTTPException, 
    status,
    Depends,
    Header,
    Query,
)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class APIPerformanceConfig:
    """Configuration for API performance optimizations."""
    # Caching
    cache_enabled: bool = True
    cache_backend: str = "memory"  # "memory", "redis"
    cache_ttl: int = 300  # seconds
    max_cache_size: int = 10000
    
    # Rate limiting
    rate_limit_enabled: bool = True
    default_rate_limit: int = 100  # requests per minute
    burst_limit: int = 20  # burst requests allowed
    
    # Compression
    compression_enabled: bool = True
    compression_min_size: int = 1024  # bytes
    compression_level: int = 6  # 1-9
    
    # Pagination
    default_page_size: int = 20
    max_page_size: int = 100
    
    # Batching
    batch_enabled: bool = True
    max_batch_size: int = 50
    
    # Async
    async_enabled: bool = True
    max_concurrent_requests: int = 100
    
    # Monitoring
    metrics_enabled: bool = True
    health_check_interval: int = 60  # seconds
    
    # Timeouts
    request_timeout: float = 30.0  # seconds
    
    @classmethod
    def from_env(cls) -> "APIPerformanceConfig":
        """Create configuration from environment variables."""
        import os
        
        return cls(
            cache_enabled=os.getenv("API_CACHE_ENABLED", "true").lower() == "true",
            cache_backend=os.getenv("API_CACHE_BACKEND", "memory"),
            cache_ttl=int(os.getenv("API_CACHE_TTL", "300")),
            max_cache_size=int(os.getenv("API_MAX_CACHE_SIZE", "10000")),
            rate_limit_enabled=os.getenv("API_RATE_LIMIT_ENABLED", "true").lower() == "true",
            default_rate_limit=int(os.getenv("API_RATE_LIMIT", "100")),
            burst_limit=int(os.getenv("API_BURST_LIMIT", "20")),
            compression_enabled=os.getenv("API_COMPRESSION_ENABLED", "true").lower() == "true",
            compression_min_size=int(os.getenv("API_COMPRESSION_MIN_SIZE", "1024")),
            compression_level=int(os.getenv("API_COMPRESSION_LEVEL", "6")),
            default_page_size=int(os.getenv("API_DEFAULT_PAGE_SIZE", "20")),
            max_page_size=int(os.getenv("API_MAX_PAGE_SIZE", "100")),
            batch_enabled=os.getenv("API_BATCH_ENABLED", "true").lower() == "true",
            max_batch_size=int(os.getenv("API_MAX_BATCH_SIZE", "50")),
            async_enabled=os.getenv("API_ASYNC_ENABLED", "true").lower() == "true",
            max_concurrent_requests=int(os.getenv("API_MAX_CONCURRENT", "100")),
            metrics_enabled=os.getenv("API_METRICS_ENABLED", "true").lower() == "true",
            health_check_interval=int(os.getenv("API_HEALTH_CHECK_INTERVAL", "60")),
            request_timeout=float(os.getenv("API_REQUEST_TIMEOUT", "30.0")),
        )


# Global configuration
config = APIPerformanceConfig.from_env()


# =============================================================================
# Enums
# =============================================================================

class CacheStrategy(str, Enum):
    """Cache strategies."""
    NONE = "none"
    MEMORY = "memory"
    REDIS = "redis"
    FILE = "file"


class CompressionType(str, Enum):
    """Compression types."""
    NONE = "none"
    GZIP = "gzip"
    DEFLATE = "deflate"
    BROTLI = "brotli"


# =============================================================================
# Response Cache
# =============================================================================

class ResponseCache:
    """
    Caches API responses to improve performance.
    """
    
    def __init__(self, config: Optional[APIPerformanceConfig] = None):
        """
        Initialize the response cache.
        
        Args:
            config: API performance configuration.
        """
        self.config = config or config
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_size = self.config.max_cache_size
        self._backend = self._get_backend()
    
    def _get_backend(self) -> Any:
        """Get the appropriate cache backend."""
        if self.config.cache_backend == "redis":
            try:
                import redis
                return redis.Redis(
                    host="localhost",
                    port=6379,
                    db=0,
                    decode_responses=True,
                )
            except ImportError:
                logger.warning("Redis not available, using memory cache")
                return None
        
        return None  # Use in-memory cache
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a cached response.
        
        Args:
            key: Cache key.
            
        Returns:
            Cached response or None.
        """
        with self._lock:
            # Try backend first
            if self._backend:
                try:
                    data = self._backend.get(key)
                    if data:
                        return json.loads(data)
                except Exception:
                    pass
            
            # Fall back to in-memory cache
            if key not in self._cache:
                return None
            
            # Check TTL
            if time.time() - self._access_times.get(key, 0) > self.config.cache_ttl:
                del self._cache[key]
                del self._access_times[key]
                return None
            
            # Update access time
            self._access_times[key] = time.time()
            
            return self._cache[key]
    
    def set(self, key: str, value: Dict[str, Any]) -> None:
        """
        Cache a response.
        
        Args:
            key: Cache key.
            value: Response to cache.
        """
        with self._lock:
            # Check if we need to evict old entries
            if len(self._cache) >= self._max_size:
                self._evict_oldest()
            
            # Store in backend
            if self._backend:
                try:
                    self._backend.setex(key, self.config.cache_ttl, json.dumps(value))
                except Exception:
                    pass
            
            # Store in memory
            self._cache[key] = value
            self._access_times[key] = time.time()
    
    def _evict_oldest(self) -> None:
        """Evict the oldest cache entry."""
        if not self._access_times:
            return
        
        # Find oldest entry
        oldest_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        
        # Remove it
        del self._cache[oldest_key]
        del self._access_times[oldest_key]
        
        # Also remove from backend
        if self._backend:
            try:
                self._backend.delete(oldest_key)
            except Exception:
                pass
    
    def delete(self, key: str) -> bool:
        """
        Delete a cached response.
        
        Args:
            key: Cache key.
            
        Returns:
            True if deleted.
        """
        with self._lock:
            deleted = False
            
            if key in self._cache:
                del self._cache[key]
                deleted = True
            
            if key in self._access_times:
                del self._access_times[key]
            
            if self._backend:
                try:
                    self._backend.delete(key)
                    deleted = True
                except Exception:
                    pass
            
            return deleted
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            
            if self._backend:
                try:
                    self._backend.flushdb()
                except Exception:
                    pass
    
    def size(self) -> int:
        """Get the cache size."""
        with self._lock:
            return len(self._cache)
    
    def cleanup(self) -> int:
        """
        Clean up expired entries.
        
        Returns:
            Number of entries removed.
        """
        with self._lock:
            removed = 0
            now = time.time()
            
            for key in list(self._access_times.keys()):
                if now - self._access_times[key] > self.config.cache_ttl:
                    del self._cache[key]
                    del self._access_times[key]
                    removed += 1
                    
                    if self._backend:
                        try:
                            self._backend.delete(key)
                        except Exception:
                            pass
            
            return removed


# Global response cache
response_cache = ResponseCache()


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Rate limiter for API endpoints.
    """
    
    def __init__(self, config: Optional[APIPerformanceConfig] = None):
        """
        Initialize the rate limiter.
        
        Args:
            config: API performance configuration.
        """
        self.config = config or config
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def check_rate_limit(self, identifier: str) -> bool:
        """
        Check if a request should be rate limited.
        
        Args:
            identifier: Client identifier (IP, API key, etc.).
            
        Returns:
            True if request is allowed.
        """
        with self._lock:
            now = time.time()
            
            # Get or initialize tokens
            if identifier not in self._tokens:
                self._tokens[identifier] = self.config.default_rate_limit
                self._last_refill[identifier] = now
            
            # Refill tokens
            elapsed = now - self._last_refill[identifier]
            rate = self.config.default_rate_limit / 60.0  # Per second
            self._tokens[identifier] = min(
                self.config.default_rate_limit + self.config.burst_limit,
                self._tokens[identifier] + elapsed * rate
            )
            self._last_refill[identifier] = now
            
            # Check if we have tokens
            if self._tokens[identifier] >= 1:
                self._tokens[identifier] -= 1
                return True
            
            return False
    
    def get_remaining(self, identifier: str) -> int:
        """
        Get remaining requests for an identifier.
        
        Args:
            identifier: Client identifier.
            
        Returns:
            Number of remaining requests.
        """
        with self._lock:
            if identifier not in self._tokens:
                return self.config.default_rate_limit
            return int(self._tokens[identifier])
    
    def reset(self, identifier: str) -> None:
        """
        Reset rate limit for an identifier.
        
        Args:
            identifier: Client identifier.
        """
        with self._lock:
            self._tokens[identifier] = self.config.default_rate_limit
            self._last_refill[identifier] = time.time()


# Global rate limiter
rate_limiter = RateLimiter()


# =============================================================================
# Request Batcher
# =============================================================================

class RequestBatcher:
    """
    Batches multiple requests into a single response for efficiency.
    """
    
    def __init__(self, config: Optional[APIPerformanceConfig] = None):
        """
        Initialize the request batcher.
        
        Args:
            config: API performance configuration.
        """
        self.config = config or config
        self._batches: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()
    
    def add_request(self, batch_id: str, request: Dict[str, Any]) -> None:
        """
        Add a request to a batch.
        
        Args:
            batch_id: Batch identifier.
            request: Request data.
        """
        with self._lock:
            if batch_id not in self._batches:
                self._batches[batch_id] = []
            
            if len(self._batches[batch_id]) < self.config.max_batch_size:
                self._batches[batch_id].append(request)
    
    def get_batch(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Get all requests in a batch.
        
        Args:
            batch_id: Batch identifier.
            
        Returns:
            List of requests.
        """
        with self._lock:
            return self._batches.get(batch_id, []).copy()
    
    def clear_batch(self, batch_id: str) -> None:
        """
        Clear a batch.
        
        Args:
            batch_id: Batch identifier.
        """
        with self._lock:
            if batch_id in self._batches:
                del self._batches[batch_id]
    
    def cleanup(self, timeout: float = 300.0) -> int:
        """
        Clean up old batches.
        
        Args:
            timeout: Timeout in seconds.
            
        Returns:
            Number of batches cleaned up.
        """
        with self._lock:
            removed = 0
            now = time.time()
            
            # This would need timestamps to work properly
            # For now, just clear empty batches
            for batch_id in list(self._batches.keys()):
                if not self._batches[batch_id]:
                    del self._batches[batch_id]
                    removed += 1
            
            return removed


# Global request batcher
request_batcher = RequestBatcher()


# =============================================================================
# Compression Middleware
# =============================================================================

class CompressionMiddleware(BaseHTTPMiddleware):
    """
    Middleware for compressing API responses.
    """
    
    def __init__(self, app, config: Optional[APIPerformanceConfig] = None):
        """
        Initialize the compression middleware.
        
        Args:
            app: FastAPI application.
            config: API performance configuration.
        """
        super().__init__(app)
        self.config = config or config
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process a request and compress the response if needed."""
        # Check if compression is enabled
        if not self.config.compression_enabled:
            return await call_next(request)
        
        # Check Accept-Encoding header
        accept_encoding = request.headers.get("Accept-Encoding", "")
        
        # Only compress if client supports it
        if "gzip" not in accept_encoding.lower():
            return await call_next(request)
        
        # Get the response
        response = await call_next(request)
        
        # Check if response should be compressed
        if not self._should_compress(response):
            return response
        
        # Compress the response
        compressed_body = self._compress(response.body)
        
        # Create new response with compressed body
        return Response(
            content=compressed_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
    
    def _should_compress(self, response: Response) -> bool:
        """Check if a response should be compressed."""
        # Don't compress if already compressed
        if response.headers.get("Content-Encoding") == "gzip":
            return False
        
        # Don't compress small responses
        if len(response.body) < self.config.compression_min_size:
            return False
        
        # Only compress certain content types
        content_type = response.media_type or ""
        compressible_types = [
            "application/json",
            "text/html",
            "text/plain",
            "text/css",
            "application/javascript",
        ]
        
        return any(ct in content_type for ct in compressible_types)
    
    def _compress(self, data: bytes) -> bytes:
        """Compress data using gzip."""
        return gzip.compress(data, compresslevel=self.config.compression_level)


# =============================================================================
# Performance Monitoring Middleware
# =============================================================================

class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """
    Middleware for monitoring API performance.
    """
    
    def __init__(self, app, config: Optional[APIPerformanceConfig] = None):
        """
        Initialize the performance monitoring middleware.
        
        Args:
            app: FastAPI application.
            config: API performance configuration.
        """
        super().__init__(app)
        self.config = config or config
        self._metrics: Dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_response_time": 0.0,
            "endpoints": {},
            "clients": {},
        }
        self._lock = threading.Lock()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process a request and monitor performance."""
        start_time = time.time()
        
        # Get client identifier
        client_ip = request.client.host if request.client else "unknown"
        
        try:
            response = await call_next(request)
            execution_time = time.time() - start_time
            
            # Record successful request
            self._record_request(
                request.url.path,
                request.method,
                client_ip,
                response.status_code,
                execution_time,
                True
            )
            
            return response
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            # Record failed request
            self._record_request(
                request.url.path,
                request.method,
                client_ip,
                500,
                execution_time,
                False
            )
            
            raise
    
    def _record_request(
        self,
        path: str,
        method: str,
        client: str,
        status_code: int,
        execution_time: float,
        success: bool
    ) -> None:
        """Record a request in metrics."""
        with self._lock:
            self._metrics["total_requests"] += 1
            
            if success and status_code < 400:
                self._metrics["successful_requests"] += 1
            else:
                self._metrics["failed_requests"] += 1
            
            self._metrics["total_response_time"] += execution_time
            
            # Record endpoint metrics
            endpoint_key = f"{method}:{path}"
            if endpoint_key not in self._metrics["endpoints"]:
                self._metrics["endpoints"][endpoint_key] = {
                    "count": 0,
                    "total_time": 0.0,
                    "success_count": 0,
                    "failure_count": 0,
                }
            
            self._metrics["endpoints"][endpoint_key]["count"] += 1
            self._metrics["endpoints"][endpoint_key]["total_time"] += execution_time
            
            if success:
                self._metrics["endpoints"][endpoint_key]["success_count"] += 1
            else:
                self._metrics["endpoints"][endpoint_key]["failure_count"] += 1
            
            # Record client metrics
            if client not in self._metrics["clients"]:
                self._metrics["clients"][client] = {
                    "count": 0,
                    "last_request": time.time(),
                }
            
            self._metrics["clients"][client]["count"] += 1
            self._metrics["clients"][client]["last_request"] = time.time()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            metrics = self._metrics.copy()
            
            # Calculate averages
            if metrics["total_requests"] > 0:
                metrics["avg_response_time"] = (
                    metrics["total_response_time"] / metrics["total_requests"]
                )
                metrics["success_rate"] = (
                    metrics["successful_requests"] / metrics["total_requests"]
                )
            else:
                metrics["avg_response_time"] = 0.0
                metrics["success_rate"] = 0.0
            
            return metrics
    
    def get_endpoint_metrics(self, path: str, method: str = "GET") -> Dict[str, Any]:
        """Get metrics for a specific endpoint."""
        with self._lock:
            endpoint_key = f"{method}:{path}"
            if endpoint_key in self._metrics["endpoints"]:
                return self._metrics["endpoints"][endpoint_key].copy()
            return {}
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_response_time": 0.0,
                "endpoints": {},
                "clients": {},
            }


# Global performance monitor
performance_monitor = PerformanceMonitoringMiddleware(None, config)


# =============================================================================
# Pagination Utilities
# =============================================================================

@dataclass
class PaginatedResponse:
    """Standard paginated response format."""
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
        }


def paginate(
    items: List[Any],
    page: int = 1,
    page_size: int = 20
) -> PaginatedResponse:
    """
    Paginate a list of items.
    
    Args:
        items: List of items to paginate.
        page: Page number (1-based).
        page_size: Number of items per page.
        
    Returns:
        PaginatedResponse with paginated items.
    """
    total = len(items)
    total_pages = (total + page_size - 1) // page_size
    
    # Calculate start and end indices
    start = (page - 1) * page_size
    end = start + page_size
    
    # Get items for this page
    page_items = items[start:end]
    
    return PaginatedResponse(
        items=page_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


# =============================================================================
# Decorators
# =============================================================================

def cached(
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None,
    unless: Optional[Callable] = None
) -> Callable:
    """
    Decorator to cache API endpoint responses.
    
    Args:
        ttl: Time-to-live in seconds (overrides config).
        key_func: Function to generate cache key.
        unless: Function that returns True if caching should be skipped.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Check if caching is enabled
            if not config.cache_enabled:
                return await func(*args, **kwargs)
            
            # Check unless condition
            if unless and unless(*args, **kwargs):
                return await func(*args, **kwargs)
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = self._generate_cache_key(func, args, kwargs)
            
            # Try to get from cache
            cached_data = response_cache.get(cache_key)
            if cached_data is not None:
                return JSONResponse(
                    content=cached_data,
                    status_code=200,
                    headers={"X-Cache": "HIT"}
                )
            
            # Execute function
            response = await func(*args, **kwargs)
            
            # Only cache successful responses
            if isinstance(response, JSONResponse) and 200 <= response.status_code < 300:
                # Cache the response
                response_cache.set(cache_key, response.body)
                
                # Add cache header
                response.headers["X-Cache"] = "MISS"
            
            return response
        
        return wrapper
    
    return decorator


def _generate_cache_key(func: Callable, args: Tuple, kwargs: Dict) -> str:
    """Generate a cache key for a function call."""
    # Get function name
    func_name = f"{func.__module__}.{func.__name__}"
    
    # Create key from arguments
    key_parts = [func_name]
    
    for arg in args:
        if isinstance(arg, Request):
            # Include request path and query params
            key_parts.append(arg.url.path)
            key_parts.append(str(arg.query_params))
        else:
            key_parts.append(str(arg))
    
    for key, value in sorted(kwargs.items()):
        key_parts.append(f"{key}={value}")
    
    # Create hash
    key = "|".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()


def rate_limited(
    limit: Optional[int] = None,
    burst: Optional[int] = None,
    identifier_func: Optional[Callable] = None
) -> Callable:
    """
    Decorator to rate limit an API endpoint.
    
    Args:
        limit: Requests per minute (overrides config).
        burst: Burst requests allowed (overrides config).
        identifier_func: Function to extract client identifier from request.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Check if rate limiting is enabled
            if not config.rate_limit_enabled:
                return await func(request, *args, **kwargs)
            
            # Get client identifier
            if identifier_func:
                identifier = identifier_func(request)
            else:
                identifier = request.client.host if request.client else "unknown"
            
            # Check rate limit
            if not rate_limiter.check_rate_limit(identifier):
                remaining = rate_limiter.get_remaining(identifier)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "retry_after": 60,
                        "remaining": remaining,
                    },
                    headers={
                        "Retry-After": "60",
                        "X-RateLimit-Remaining": str(remaining),
                    }
                )
            
            # Add rate limit headers to response
            response = await func(request, *args, **kwargs)
            
            if isinstance(response, Response):
                remaining = rate_limiter.get_remaining(identifier)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Limit"] = str(
                    config.default_rate_limit + config.burst_limit
                )
            
            return response
        
        return wrapper
    
    return decorator


def compress_response(
    min_size: Optional[int] = None,
    level: Optional[int] = None
) -> Callable:
    """
    Decorator to compress API responses.
    
    Args:
        min_size: Minimum response size to compress (overrides config).
        level: Compression level (overrides config).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            response = await func(request, *args, **kwargs)
            
            # Check if we should compress
            if not config.compression_enabled:
                return response
            
            # Check Accept-Encoding
            accept_encoding = request.headers.get("Accept-Encoding", "")
            if "gzip" not in accept_encoding.lower():
                return response
            
            # Check response size
            min_size = min_size or config.compression_min_size
            if isinstance(response, JSONResponse):
                content = response.body
                if len(content) >= min_size:
                    # Compress
                    level = level or config.compression_level
                    compressed = gzip.compress(content, compresslevel=level)
                    
                    # Return compressed response
                    return Response(
                        content=compressed,
                        status_code=response.status_code,
                        headers={
                            **response.headers,
                            "Content-Encoding": "gzip",
                            "Vary": "Accept-Encoding",
                        },
                        media_type=response.media_type,
                    )
            
            return response
        
        return wrapper
    
    return decorator


def timeout(seconds: Optional[float] = None) -> Callable:
    """
    Decorator to add timeout to API endpoints.
    
    Args:
        seconds: Timeout in seconds (overrides config).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            timeout_seconds = seconds or config.request_timeout
            
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=status.HTTP_408_REQUEST_TIMEOUT,
                    detail={"error": "Request timeout"}
                )
        
        return wrapper
    
    return decorator


# =============================================================================
# Health Check Endpoints
# =============================================================================

class HealthCheckRouter:
    """
    Router for health check and monitoring endpoints.
    """
    
    def __init__(self):
        """Initialize the health check router."""
        self.router = FastAPI()
        self._setup_routes()
    
    def _setup_routes(self) -> None:
        """Set up health check routes."""
        
        @self.router.get("/health")
        async def health_check():
            """Basic health check endpoint."""
            return {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        @self.router.get("/health/detailed")
        async def detailed_health_check():
            """Detailed health check with component status."""
            # Check database
            db_status = await self._check_database()
            
            # Check cache
            cache_status = self._check_cache()
            
            # Check rate limiter
            rate_limiter_status = self._check_rate_limiter()
            
            return {
                "status": "healthy" if all([
                    db_status["healthy"],
                    cache_status["healthy"],
                    rate_limiter_status["healthy"]
                ]) else "degraded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "components": {
                    "database": db_status,
                    "cache": cache_status,
                    "rate_limiter": rate_limiter_status,
                },
                "metrics": performance_monitor.get_metrics(),
            }
        
        @self.router.get("/metrics")
        async def get_metrics():
            """Get performance metrics."""
            return performance_monitor.get_metrics()
        
        @self.router.get("/status")
        async def get_status():
            """Get API status and configuration."""
            return {
                "name": "Open Omniscience API",
                "version": "0.02",
                "status": "running",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "cache_enabled": config.cache_enabled,
                    "cache_backend": config.cache_backend,
                    "rate_limit_enabled": config.rate_limit_enabled,
                    "compression_enabled": config.compression_enabled,
                    "async_enabled": config.async_enabled,
                },
                "metrics": performance_monitor.get_metrics(),
            }
    
    async def _check_database(self) -> Dict[str, Any]:
        """Check database health."""
        try:
            # Import here to avoid circular imports
            from src.database.models import get_session
            
            session = get_session()
            # Try a simple query
            session.execute("SELECT 1")
            session.close()
            
            return {
                "healthy": True,
                "message": "Database connection successful",
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e),
            }
    
    def _check_cache(self) -> Dict[str, Any]:
        """Check cache health."""
        try:
            # Test cache
            test_key = "health_check_test"
            test_value = {"test": "data"}
            
            response_cache.set(test_key, test_value)
            cached = response_cache.get(test_key)
            response_cache.delete(test_key)
            
            if cached == test_value:
                return {
                    "healthy": True,
                    "message": "Cache working correctly",
                    "size": response_cache.size(),
                }
            else:
                return {
                    "healthy": False,
                    "message": "Cache read/write test failed",
                }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e),
            }
    
    def _check_rate_limiter(self) -> Dict[str, Any]:
        """Check rate limiter health."""
        try:
            # Test rate limiter
            test_id = "health_check_test"
            
            # Should allow first request
            allowed1 = rate_limiter.check_rate_limit(test_id)
            
            # Reset for test
            rate_limiter.reset(test_id)
            
            # Should allow after reset
            allowed2 = rate_limiter.check_rate_limit(test_id)
            
            if allowed1 and allowed2:
                return {
                    "healthy": True,
                    "message": "Rate limiter working correctly",
                }
            else:
                return {
                    "healthy": False,
                    "message": "Rate limiter test failed",
                }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e),
            }
    
    def get_router(self) -> FastAPI:
        """Get the router instance."""
        return self.router


# Global health check router
health_check_router = HealthCheckRouter()


# =============================================================================
# API Factory
# =============================================================================

def create_optimized_app() -> FastAPI:
    """
    Create a FastAPI application with performance optimizations.
    
    Returns:
        FastAPI application instance.
    """
    app = FastAPI(
        title="Open Omniscience API",
        description="Global Intelligence Platform for Investigative Journalism",
        version="0.02",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add compression middleware
    if config.compression_enabled:
        app.add_middleware(CompressionMiddleware, config=config)
    
    # Add performance monitoring middleware
    if config.metrics_enabled:
        app.add_middleware(PerformanceMonitoringMiddleware, config=config)
    
    # Mount health check router
    app.mount("/api/health", health_check_router.get_router())
    
    return app


# =============================================================================
# Utility Functions
# =============================================================================

def get_cache_key(
    request: Request,
    include_headers: List[str] = None,
    exclude_params: List[str] = None
) -> str:
    """
    Generate a cache key from a request.
    
    Args:
        request: FastAPI request.
        include_headers: List of headers to include in key.
        exclude_params: List of query parameters to exclude.
        
    Returns:
        Cache key string.
    """
    include_headers = include_headers or []
    exclude_params = exclude_params or []
    
    key_parts = [
        request.method,
        request.url.path,
    ]
    
    # Add query parameters (excluding specified ones)
    query_params = dict(request.query_params)
    for param in exclude_params:
        query_params.pop(param, None)
    
    if query_params:
        key_parts.append(str(sorted(query_params.items())))
    
    # Add headers
    for header in include_headers:
        value = request.headers.get(header)
        if value:
            key_parts.append(f"{header}:{value}")
    
    # Create hash
    key = "|".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()


def get_client_identifier(request: Request) -> str:
    """
    Get a unique identifier for a client.
    
    Args:
        request: FastAPI request.
        
    Returns:
        Client identifier string.
    """
    # Try to get from API key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key}"
    
    # Fall back to IP address
    return request.client.host if request.client else "unknown"


def create_paginated_response(
    items: List[Any],
    total: int,
    page: int,
    page_size: int
) -> PaginatedResponse:
    """
    Create a paginated response.
    
    Args:
        items: List of items for this page.
        total: Total number of items.
        page: Current page number.
        page_size: Number of items per page.
        
    Returns:
        PaginatedResponse object.
    """
    total_pages = (total + page_size - 1) // page_size
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Configuration
    "APIPerformanceConfig",
    "config",
    # Enums
    "CacheStrategy",
    "CompressionType",
    # Data models
    "PaginatedResponse",
    # Services
    "ResponseCache",
    "response_cache",
    "RateLimiter",
    "rate_limiter",
    "RequestBatcher",
    "request_batcher",
    "PerformanceMonitoringMiddleware",
    "performance_monitor",
    # Middleware
    "CompressionMiddleware",
    # Utilities
    "paginate",
    "create_paginated_response",
    "get_cache_key",
    "get_client_identifier",
    # Decorators
    "cached",
    "rate_limited",
    "compress_response",
    "timeout",
    # Router
    "HealthCheckRouter",
    "health_check_router",
    # Factory
    "create_optimized_app",
]
