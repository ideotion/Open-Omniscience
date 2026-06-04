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
Database Optimization Module for Open Omniscience

This module provides comprehensive database performance optimizations including:
- Advanced indexing strategies
- Query optimization utilities
- Connection pooling management
- Performance monitoring
- Database-specific optimizations

Author: Ideotion
"""

import time
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, TypeVar
from dataclasses import dataclass, field
from contextlib import contextmanager
from enum import Enum
from functools import wraps
import hashlib
import json

from sqlalchemy import text, func, select, and_, or_, not_, desc, asc, between, distinct
from sqlalchemy.orm import Session, joinedload, selectinload, contains_eager
from sqlalchemy.sql import Select

logger = logging.getLogger(__name__)

T = TypeVar('T')


# =============================================================================
# Database Type Definitions
# =============================================================================

class DatabaseType(str, Enum):
    """Supported database types."""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


@dataclass
class QueryStats:
    """Statistics for query performance."""
    query: str
    execution_time: float
    rows_returned: int
    rows_examined: int
    cache_hit: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query[:100] + "..." if len(self.query) > 100 else self.query,
            "execution_time_ms": round(self.execution_time * 1000, 2),
            "rows_returned": self.rows_returned,
            "rows_examined": self.rows_examined,
            "cache_hit": self.cache_hit
        }


@dataclass
class IndexRecommendation:
    """Recommendation for database index."""
    table: str
    columns: List[str]
    index_name: str
    index_type: str = "BTREE"
    priority: int = 1  # 1-5, 5 being highest
    reason: str = ""
    
    def create_sql(self, database_type: DatabaseType = DatabaseType.SQLITE) -> str:
        """Generate SQL to create this index."""
        if database_type == DatabaseType.SQLITE:
            return f'CREATE INDEX IF NOT EXISTS {self.index_name} ON {self.table} ({", ".join(self.columns)})'
        elif database_type == DatabaseType.POSTGRESQL:
            return f'CREATE INDEX IF NOT EXISTS {self.index_name} ON {self.table} USING {self.index_type} ({", ".join(self.columns)})'
        else:
            return f'CREATE INDEX {self.index_name} ON {self.table} ({", ".join(self.columns)})'


# =============================================================================
# Query Optimization Utilities
# =============================================================================

class QueryOptimizer:
    """
    Optimizes SQLAlchemy queries for better performance.
    
    This class provides methods to analyze and optimize database queries,
    including automatic indexing recommendations, query rewriting, and
    performance monitoring.
    """
    
    def __init__(self, session: Session, database_type: DatabaseType = DatabaseType.SQLITE):
        """
        Initialize the query optimizer.
        
        Args:
            session: SQLAlchemy session.
            database_type: Type of database being used.
        """
        self.session = session
        self.database_type = database_type
        self._query_cache: Dict[str, Tuple[Any, float]] = {}
        self._index_recommendations: List[IndexRecommendation] = []
        self._slow_queries: List[QueryStats] = []
        self._min_query_time = 0.1  # Track queries slower than 100ms
    
    def analyze_query(self, query: Select) -> QueryStats:
        """
        Analyze a query and return performance statistics.
        
        Args:
            query: SQLAlchemy Select query to analyze.
            
        Returns:
            QueryStats with performance information.
        """
        start_time = time.time()
        
        # Execute the query
        result = self.session.execute(query)
        rows = result.fetchall()
        
        execution_time = time.time() - start_time
        
        # Get query string
        query_str = str(query)
        
        # Check cache
        cache_key = hashlib.md5(query_str.encode()).hexdigest()
        cache_hit = cache_key in self._query_cache
        
        # Store in cache
        self._query_cache[cache_key] = (rows, execution_time)
        
        # Record slow queries
        if execution_time > self._min_query_time:
            stats = QueryStats(
                query=query_str,
                execution_time=execution_time,
                rows_returned=len(rows),
                rows_examined=len(rows),  # Would need EXPLAIN for accurate count
                cache_hit=cache_hit
            )
            self._slow_queries.append(stats)
            
            # Analyze for potential index recommendations
            self._analyze_for_indexes(query_str)
        
        return QueryStats(
            query=query_str,
            execution_time=execution_time,
            rows_returned=len(rows),
            rows_examined=len(rows),
            cache_hit=cache_hit
        )
    
    def _analyze_for_indexes(self, query_str: str) -> None:
        """
        Analyze a query string for potential index recommendations.
        
        Args:
            query_str: The SQL query string to analyze.
        """
        # Convert to lowercase for case-insensitive matching
        query_lower = query_str.lower()
        
        # Look for WHERE clauses with common patterns
        if "where" in query_lower:
            # Extract table and column information
            if "articles" in query_lower:
                if "source_id" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="articles",
                        columns=["source_id"],
                        index_name="idx_articles_source_id",
                        priority=5,
                        reason="Frequent filtering by source_id"
                    ))
                if "published_at" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="articles",
                        columns=["published_at"],
                        index_name="idx_articles_published_at",
                        priority=5,
                        reason="Frequent filtering by publication date"
                    ))
                if "canonical_url" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="articles",
                        columns=["canonical_url"],
                        index_name="idx_articles_canonical_url",
                        priority=5,
                        reason="Frequent lookups by canonical URL for deduplication"
                    ))
                if "hash" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="articles",
                        columns=["hash"],
                        index_name="idx_articles_hash",
                        priority=5,
                        reason="Frequent lookups by hash for deduplication"
                    ))
            
            if "sources" in query_lower:
                if "domain" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="sources",
                        columns=["domain"],
                        index_name="idx_sources_domain",
                        priority=5,
                        reason="Frequent lookups by domain"
                    ))
                if "enabled" in query_lower:
                    self._index_recommendations.append(IndexRecommendation(
                        table="sources",
                        columns=["enabled"],
                        index_name="idx_sources_enabled",
                        priority=4,
                        reason="Frequent filtering by enabled status"
                    ))
        
        # Look for JOIN patterns
        if "join" in query_lower:
            # Recommend indexes for join columns
            if "articles" in query_lower and "sources" in query_lower:
                self._index_recommendations.append(IndexRecommendation(
                    table="articles",
                    columns=["source_id"],
                    index_name="idx_articles_source_id_join",
                    priority=5,
                    reason="Join column should be indexed"
                ))
        
        # Look for ORDER BY patterns
        if "order by" in query_lower:
            if "published_at desc" in query_lower or "published_at asc" in query_lower:
                self._index_recommendations.append(IndexRecommendation(
                    table="articles",
                    columns=["published_at"],
                    index_name="idx_articles_published_at_order",
                    priority=4,
                    reason="Sorting by published_at benefits from index"
                ))
    
    def get_index_recommendations(self) -> List[IndexRecommendation]:
        """Get all index recommendations."""
        # Remove duplicates and sort by priority
        unique_recommendations = {}
        for rec in self._index_recommendations:
            key = (rec.table, tuple(rec.columns))
            if key not in unique_recommendations or rec.priority > unique_recommendations[key].priority:
                unique_recommendations[key] = rec
        
        return sorted(unique_recommendations.values(), key=lambda x: x.priority, reverse=True)
    
    def get_slow_queries(self) -> List[QueryStats]:
        """Get all slow queries."""
        return sorted(self._slow_queries, key=lambda x: x.execution_time, reverse=True)
    
    def clear_cache(self) -> None:
        """Clear the query cache."""
        self._query_cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._query_cache),
            "slow_queries": len(self._slow_queries),
            "index_recommendations": len(self._index_recommendations)
        }


# =============================================================================
# Eager Loading Utilities
# =============================================================================

def with_relationships(query: Select, relationships: List[str]) -> Select:
    """
    Add eager loading for relationships to avoid N+1 queries.
    
    Args:
        query: The base query.
        relationships: List of relationship names to eager load.
        
    Returns:
        Query with eager loading configured.
    """
    for relationship in relationships:
        # Split nested relationships
        parts = relationship.split('.')
        
        if len(parts) == 1:
            # Simple relationship
            query = query.options(joinedload(parts[0]))
        else:
            # Nested relationship
            current = parts[0]
            for part in parts[1:]:
                current = current + "." + part
            query = query.options(joinedload(parts[0]).joinedload(part))
    
    return query


def with_selected_relationships(query: Select, relationships: List[str]) -> Select:
    """
    Add selectin loading for relationships (more efficient for many-to-one).
    
    Args:
        query: The base query.
        relationships: List of relationship names to selectin load.
        
    Returns:
        Query with selectin loading configured.
    """
    for relationship in relationships:
        query = query.options(selectinload(relationship))
    return query


# =============================================================================
# Batch Processing Utilities
# =============================================================================

def batch_query(
    query: Select,
    batch_size: int = 1000,
    process_func: Callable[[List[T]], None] = None
) -> None:
    """
    Process a large query in batches to avoid memory issues.
    
    Args:
        query: SQLAlchemy query to execute in batches.
        batch_size: Number of items per batch.
        process_func: Function to process each batch of results.
    """
    offset = 0
    
    while True:
        # Get a batch of results
        batch_query = query.offset(offset).limit(batch_size)
        results = query.session.execute(batch_query).scalars().all()
        
        if not results:
            break
        
        # Process the batch
        process_func(results)
        
        # Move to next batch
        offset += batch_size
        
        # Log progress
        if offset % (batch_size * 10) == 0:
            logger.info(f"Processed {offset} items...")


def stream_query(query: Select, process_func: Callable[[T], None]) -> None:
    """
    Stream query results one at a time for memory efficiency.
    
    Args:
        query: SQLAlchemy query to stream.
        process_func: Function to process each individual result.
    """
    result = query.session.execute(query)
    
    for row in result.scalars():
        process_func(row)


# =============================================================================
# Query Building Utilities
# =============================================================================

def build_search_query(
    base_query: Select,
    search_term: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
    limit: Optional[int] = None,
    offset: int = 0
) -> Select:
    """
    Build a comprehensive search query with filters and sorting.
    
    Args:
        base_query: The base query to start with.
        search_term: Optional search term for full-text search.
        filters: Dictionary of filter conditions.
        sort_by: Column name to sort by.
        sort_order: Sort order ('asc' or 'desc').
        limit: Maximum number of results.
        offset: Offset for pagination.
        
    Returns:
        Optimized query with all conditions applied.
    """
    query = base_query
    
    # Apply search term
    if search_term:
        # This would be replaced with actual full-text search implementation
        query = query.where(
            or_(
                base_query.column_descriptions['title'].ilike(f"%{search_term}%"),
                base_query.column_descriptions['content'].ilike(f"%{search_term}%")
            )
        )
    
    # Apply filters
    if filters:
        for field, value in filters.items():
            if isinstance(value, (list, tuple)):
                # IN clause for multiple values
                column = getattr(base_query.column_descriptions, field, None)
                if column:
                    query = query.where(column.in_(value))
            elif value is not None:
                # Equality filter
                column = getattr(base_query.column_descriptions, field, None)
                if column:
                    query = query.where(column == value)
    
    # Apply sorting
    if sort_by:
        column = getattr(base_query.column_descriptions, sort_by, None)
        if column:
            if sort_order.lower() == "desc":
                query = query.order_by(desc(column))
            else:
                query = query.order_by(asc(column))
    
    # Apply pagination
    if limit is not None:
        query = query.limit(limit)
    if offset > 0:
        query = query.offset(offset)
    
    return query


# =============================================================================
# Database-Specific Optimizations
# =============================================================================

class DatabaseOptimizer:
    """
    Database-specific optimization utilities.
    """
    
    def __init__(self, database_url: str):
        """
        Initialize the database optimizer.
        
        Args:
            database_url: The database connection URL.
        """
        self.database_url = database_url
        self.database_type = self._detect_database_type()
    
    def _detect_database_type(self) -> DatabaseType:
        """Detect the database type from the URL."""
        if self.database_url.startswith("sqlite"):
            return DatabaseType.SQLITE
        elif self.database_url.startswith("postgresql"):
            return DatabaseType.POSTGRESQL
        elif self.database_url.startswith("mysql"):
            return DatabaseType.MYSQL
        else:
            return DatabaseType.SQLITE
    
    def get_optimization_recommendations(self) -> List[str]:
        """Get database-specific optimization recommendations."""
        recommendations = []
        
        if self.database_type == DatabaseType.SQLITE:
            recommendations.extend([
                "Use WAL mode for better concurrency: PRAGMA journal_mode=WAL;",
                "Increase cache size: PRAGMA cache_size=-20000 (20MB)",
                "Enable synchronous=NORMAL for better performance: PRAGMA synchronous=NORMAL;",
                "Consider using temp_store=MEMORY: PRAGMA temp_store=MEMORY;",
                "Vacuum regularly to maintain performance: VACUUM;",
                "Analyze query patterns and add appropriate indexes",
                "Consider switching to PostgreSQL for high-concurrency workloads"
            ])
        
        elif self.database_type == DatabaseType.POSTGRESQL:
            recommendations.extend([
                "Set appropriate work_mem based on your workload",
                "Configure maintenance_work_mem for VACUUM operations",
                "Set effective_cache_size to 50-75% of available RAM",
                "Configure shared_buffers to 25% of available RAM",
                "Use connection pooling with appropriate pool size",
                "Consider partitioning large tables by date ranges",
                "Implement table inheritance for large, related datasets",
                "Use materialized views for complex, frequently accessed queries",
                "Consider using TimescaleDB extension for time-series data"
            ])
        
        return recommendations
    
    def get_connection_string(self, **kwargs: Any) -> str:
        """Get an optimized connection string."""
        if self.database_type == DatabaseType.SQLITE:
            # Add SQLite-specific optimizations
            base_url = self.database_url
            if "?" in base_url:
                return base_url + "&" + "&".join(f"{k}={v}" for k, v in kwargs.items())
            else:
                return base_url + "?" + "&".join(f"{k}={v}" for k, v in kwargs.items())
        else:
            return self.database_url


# =============================================================================
# Performance Monitoring
# =============================================================================

@dataclass
class DatabaseMetrics:
    """Database performance metrics."""
    query_count: int = 0
    total_execution_time: float = 0.0
    slow_query_count: int = 0
    connection_count: int = 0
    active_connections: int = 0
    cache_hit_rate: float = 0.0
    
    def record_query(self, execution_time: float, is_slow: bool = False) -> None:
        """Record a query execution."""
        self.query_count += 1
        self.total_execution_time += execution_time
        if is_slow:
            self.slow_query_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_count": self.query_count,
            "total_execution_time": round(self.total_execution_time, 4),
            "avg_execution_time": round(self.total_execution_time / self.query_count, 4) if self.query_count > 0 else 0,
            "slow_query_count": self.slow_query_count,
            "slow_query_percentage": round((self.slow_query_count / self.query_count * 100), 2) if self.query_count > 0 else 0,
            "connection_count": self.connection_count,
            "active_connections": self.active_connections,
            "cache_hit_rate": round(self.cache_hit_rate, 4)
        }


class DatabaseMonitor:
    """Monitor database performance."""
    
    def __init__(self):
        self.metrics = DatabaseMetrics()
        self._query_times: List[float] = []
    
    def record_query(self, execution_time: float, is_slow: bool = False) -> None:
        """Record a query execution."""
        self.metrics.record_query(execution_time, is_slow)
        self._query_times.append(execution_time)
    
    def get_percentile(self, percentile: float) -> float:
        """Get the nth percentile of query times."""
        if not self._query_times:
            return 0.0
        
        sorted_times = sorted(self._query_times)
        index = int(len(sorted_times) * percentile / 100)
        return sorted_times[min(index, len(sorted_times) - 1)]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        metrics_dict = self.metrics.to_dict()
        metrics_dict["p50_query_time"] = round(self.get_percentile(50), 4)
        metrics_dict["p90_query_time"] = round(self.get_percentile(90), 4)
        metrics_dict["p99_query_time"] = round(self.get_percentile(99), 4)
        return metrics_dict


# Global database monitor
database_monitor = DatabaseMonitor()


# =============================================================================
# Decorators
# =============================================================================

def monitor_query(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to monitor query performance."""
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Record in monitor
            is_slow = execution_time > 0.1
            database_monitor.record_query(execution_time, is_slow)
            
            return result
        except Exception as e:
            database_monitor.record_query(time.time() - start_time, True)
            raise
    
    return wrapper


def cached_query(ttl: float = 300.0):
    """Decorator to cache query results."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: Dict[str, Tuple[T, float]] = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Create cache key from function name and arguments
            cache_key = hashlib.md5(f"{func.__name__}{args}{kwargs}".encode()).hexdigest()
            
            # Check cache
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if time.time() - timestamp < ttl:
                    database_monitor.record_query(0.001, False)  # Cache hit
                    return result
            
            # Execute function
            start_time = time.time()
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Cache result
            cache[cache_key] = (result, time.time())
            
            # Record in monitor
            database_monitor.record_query(execution_time)
            
            return result
        
        return wrapper
    
    return decorator


__all__ = [
    # Type definitions
    'DatabaseType', 'QueryStats', 'IndexRecommendation',
    
    # Query optimization
    'QueryOptimizer',
    
    # Eager loading
    'with_relationships', 'with_selected_relationships',
    
    # Batch processing
    'batch_query', 'stream_query',
    
    # Query building
    'build_search_query',
    
    # Database-specific
    'DatabaseOptimizer',
    
    # Monitoring
    'DatabaseMetrics', 'DatabaseMonitor', 'database_monitor',
    
    # Decorators
    'monitor_query', 'cached_query',
]
