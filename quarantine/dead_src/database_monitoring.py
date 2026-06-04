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
Database Monitoring Module for Open Omniscience

This module provides comprehensive database monitoring capabilities including:
- Query performance tracking
- Connection pool monitoring
- Database health checks
- Slow query detection and logging
- Performance metrics collection
- Alerting for database issues

Author: Ideotion
"""

import time
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from contextlib import contextmanager
from collections import defaultdict
import json
import hashlib

from sqlalchemy import text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# =============================================================================
# Monitoring Configuration
# =============================================================================

@dataclass
class MonitoringConfig:
    """Configuration for database monitoring."""
    enabled: bool = True
    slow_query_threshold: float = 0.1  # Seconds
    long_running_threshold: float = 1.0  # Seconds
    max_query_history: int = 1000  # Maximum number of queries to keep in history
    max_slow_queries: int = 100  # Maximum number of slow queries to keep
    log_slow_queries: bool = True
    log_long_running_queries: bool = True
    collect_metrics: bool = True
    health_check_interval: int = 60  # Seconds
    
    # Alerting configuration
    alert_on_slow_queries: bool = True
    alert_on_long_running: bool = True
    alert_on_connection_issues: bool = True
    slow_query_threshold_count: int = 5  # Alert after this many slow queries
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "slow_query_threshold": self.slow_query_threshold,
            "long_running_threshold": self.long_running_threshold,
            "max_query_history": self.max_query_history,
            "max_slow_queries": self.max_slow_queries,
            "log_slow_queries": self.log_slow_queries,
            "log_long_running_queries": self.log_long_running_queries,
            "collect_metrics": self.collect_metrics,
            "health_check_interval": self.health_check_interval,
            "alert_on_slow_queries": self.alert_on_slow_queries,
            "alert_on_long_running": self.alert_on_long_running,
            "alert_on_connection_issues": self.alert_on_connection_issues,
            "slow_query_threshold_count": self.slow_query_threshold_count,
        }


# Default monitoring configuration
DEFAULT_MONITORING_CONFIG = MonitoringConfig()


# =============================================================================
# Query Statistics
# =============================================================================

@dataclass
class QueryInfo:
    """Information about a database query."""
    query: str
    execution_time: float
    start_time: datetime
    end_time: datetime
    success: bool = True
    error: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    connection_id: Optional[str] = None
    
    @property
    def is_slow(self) -> bool:
        """Check if this query is considered slow."""
        return self.execution_time >= DEFAULT_MONITORING_CONFIG.slow_query_threshold
    
    @property
    def is_long_running(self) -> bool:
        """Check if this query is considered long-running."""
        return self.execution_time >= DEFAULT_MONITORING_CONFIG.long_running_threshold
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query[:200] + "..." if len(self.query) > 200 else self.query,
            "execution_time_ms": round(self.execution_time * 1000, 2),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "success": self.success,
            "error": self.error,
            "is_slow": self.is_slow,
            "is_long_running": self.is_long_running,
            "connection_id": self.connection_id,
        }


# =============================================================================
# Connection Statistics
# =============================================================================

@dataclass
class ConnectionInfo:
    """Information about a database connection."""
    connection_id: str
    created_at: datetime
    last_used: datetime
    query_count: int = 0
    total_execution_time: float = 0.0
    is_active: bool = True
    
    @property
    def avg_execution_time(self) -> float:
        """Calculate average execution time."""
        return self.total_execution_time / self.query_count if self.query_count > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "connection_id": self.connection_id,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "query_count": self.query_count,
            "total_execution_time_ms": round(self.total_execution_time * 1000, 2),
            "avg_execution_time_ms": round(self.avg_execution_time * 1000, 2),
            "is_active": self.is_active,
        }


# =============================================================================
# Database Health Status
# =============================================================================

@dataclass
class DatabaseHealth:
    """Health status of the database."""
    status: str = "healthy"  # "healthy", "degraded", "unhealthy"
    last_check: datetime = field(default_factory=datetime.now)
    response_time: float = 0.0
    connection_count: int = 0
    active_connection_count: int = 0
    error_count: int = 0
    slow_query_count: int = 0
    long_running_query_count: int = 0
    disk_usage: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status,
            "last_check": self.last_check.isoformat(),
            "response_time_ms": round(self.response_time * 1000, 2),
            "connection_count": self.connection_count,
            "active_connection_count": self.active_connection_count,
            "error_count": self.error_count,
            "slow_query_count": self.slow_query_count,
            "long_running_query_count": self.long_running_query_count,
            "disk_usage": self.disk_usage,
        }


# =============================================================================
# Main Monitoring Class
# =============================================================================

class DatabaseMonitor:
    """
    Main database monitoring class.
    
    This class collects and manages database performance metrics,
    tracks slow queries, and provides health monitoring capabilities.
    """
    
    def __init__(self, engine: Engine, config: Optional[MonitoringConfig] = None):
        """
        Initialize the database monitor.
        
        Args:
            engine: SQLAlchemy engine to monitor.
            config: Monitoring configuration.
        """
        self.engine = engine
        self.config = config or DEFAULT_MONITORING_CONFIG
        self._lock = threading.Lock()
        
        # Query tracking
        self._query_history: List[QueryInfo] = []
        self._slow_queries: List[QueryInfo] = []
        self._long_running_queries: List[QueryInfo] = []
        
        # Connection tracking
        self._connections: Dict[str, ConnectionInfo] = {}
        
        # Metrics
        self._metrics: Dict[str, Any] = {
            "total_queries": 0,
            "total_execution_time": 0.0,
            "total_errors": 0,
            "total_slow_queries": 0,
            "total_long_running_queries": 0,
            "peak_connections": 0,
            "current_connections": 0,
        }
        
        # Health
        self._health = DatabaseHealth()
        self._last_health_check = datetime.now()
        
        # Alert tracking
        self._alerts: List[Dict[str, Any]] = []
        self._slow_query_count = 0
        
        # Setup event listeners
        self._setup_event_listeners()
    
    def _setup_event_listeners(self) -> None:
        """Setup SQLAlchemy event listeners for monitoring."""
        if not self.config.enabled:
            return
        
        # Listen for before_cursor_execute events
        @event.listens_for(self.engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._handle_before_execute(conn, cursor, statement, parameters, context)
        
        # Listen for after_cursor_execute events
        @event.listens_for(self.engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._handle_after_execute(conn, cursor, statement, parameters, context)
        
        # Listen for error events (dbapi_error was removed in SQLAlchemy 2.0)
        # Note: 'error' event is not available in all SQLAlchemy versions/backends
        # For now, we skip this event to maintain compatibility
        # @event.listens_for(self.engine, "error")
        # def error_handler(connection, cursor, statement, parameters, context, executemany):
        #     self._handle_error(connection, cursor, statement, parameters, context)
        
        # Listen for connect events
        @event.listens_for(self.engine, "connect")
        def connect(dbapi_connection, connection_record):
            self._handle_connect(dbapi_connection, connection_record)
        
        # Listen for close events
        @event.listens_for(self.engine, "close")
        def close(dbapi_connection, connection_record):
            self._handle_close(dbapi_connection, connection_record)
        
        # Listen for checkout events (connection from pool)
        @event.listens_for(self.engine, "checkout")
        def checkout(dbapi_connection, connection_record, connection_proxy):
            self._handle_checkout(dbapi_connection, connection_record, connection_proxy)
        
        # Listen for checkin events (connection to pool)
        @event.listens_for(self.engine, "checkin")
        def checkin(dbapi_connection, connection_record):
            self._handle_checkin(dbapi_connection, connection_record)
    
    def _handle_before_execute(
        self, 
        conn: Any, 
        cursor: Any, 
        statement: str, 
        parameters: Any, 
        context: Any
    ) -> None:
        """Handle before cursor execute event."""
        if not self.config.enabled:
            return
        
        connection_id = str(id(conn))
        
        with self._lock:
            # Create or update connection info
            if connection_id not in self._connections:
                self._connections[connection_id] = ConnectionInfo(
                    connection_id=connection_id,
                    created_at=datetime.now(),
                    last_used=datetime.now(),
                )
            
            # Update connection last used time
            self._connections[connection_id].last_used = datetime.now()
            self._connections[connection_id].is_active = True
            
            # Store start time in context
            context._start_time = time.time()
            context._query_info = {
                "statement": statement,
                "parameters": parameters,
                "connection_id": connection_id,
            }
    
    def _handle_after_execute(
        self, 
        conn: Any, 
        cursor: Any, 
        statement: str, 
        parameters: Any, 
        context: Any
    ) -> None:
        """Handle after cursor execute event."""
        if not self.config.enabled:
            return
        
        # Get query info from context
        if not hasattr(context, "_start_time") or not hasattr(context, "_query_info"):
            return
        
        start_time = context._start_time
        query_info = context._query_info
        
        execution_time = time.time() - start_time
        now = datetime.now()
        
        query = QueryInfo(
            query=query_info["statement"],
            execution_time=execution_time,
            start_time=now - timedelta(seconds=execution_time),
            end_time=now,
            success=True,
            connection_id=query_info["connection_id"],
            parameters=query_info.get("parameters"),
        )
        
        with self._lock:
            # Update metrics
            self._metrics["total_queries"] += 1
            self._metrics["total_execution_time"] += execution_time
            
            # Track connection
            connection_id = query_info["connection_id"]
            if connection_id in self._connections:
                self._connections[connection_id].query_count += 1
                self._connections[connection_id].total_execution_time += execution_time
            
            # Add to query history
            self._query_history.append(query)
            if len(self._query_history) > self.config.max_query_history:
                self._query_history = self._query_history[-self.config.max_query_history:]
            
            # Track slow queries
            if query.is_slow:
                self._slow_queries.append(query)
                self._metrics["total_slow_queries"] += 1
                if len(self._slow_queries) > self.config.max_slow_queries:
                    self._slow_queries = self._slow_queries[-self.config.max_slow_queries:]
                
                if self.config.log_slow_queries:
                    logger.warning(f"Slow query ({execution_time:.3f}s): {query.query[:100]}...")
                
                # Check for alerting
                self._slow_query_count += 1
                if (self.config.alert_on_slow_queries and 
                    self._slow_query_count >= self.config.slow_query_threshold_count):
                    self._trigger_alert(
                        "slow_queries",
                        f"Detected {self._slow_query_count} slow queries",
                        severity="warning"
                    )
                    self._slow_query_count = 0
            
            # Track long-running queries
            if query.is_long_running:
                self._long_running_queries.append(query)
                self._metrics["total_long_running_queries"] += 1
                
                if self.config.log_long_running_queries:
                    logger.error(f"Long-running query ({execution_time:.3f}s): {query.query[:100]}...")
                
                if self.config.alert_on_long_running:
                    self._trigger_alert(
                        "long_running_query",
                        f"Long-running query detected: {execution_time:.3f}s",
                        severity="error",
                        query_info=query.to_dict()
                    )
    
    def _handle_error(
        self, 
        connection: Any, 
        cursor: Any, 
        statement: str, 
        parameters: Any, 
        context: Any
    ) -> None:
        """Handle database error event."""
        if not self.config.enabled:
            return
        
        with self._lock:
            self._metrics["total_errors"] += 1
            
            if self.config.alert_on_connection_issues:
                self._trigger_alert(
                    "database_error",
                    f"Database error: {statement[:100]}...",
                    severity="error"
                )
    
    def _handle_connect(self, dbapi_connection: Any, connection_record: Any) -> None:
        """Handle connection event."""
        if not self.config.enabled:
            return
        
        connection_id = str(id(dbapi_connection))
        
        with self._lock:
            self._connections[connection_id] = ConnectionInfo(
                connection_id=connection_id,
                created_at=datetime.now(),
                last_used=datetime.now(),
                is_active=True,
            )
            
            current_connections = len(self._connections)
            self._metrics["current_connections"] = current_connections
            if current_connections > self._metrics["peak_connections"]:
                self._metrics["peak_connections"] = current_connections
    
    def _handle_close(self, dbapi_connection: Any, connection_record: Any) -> None:
        """Handle close event."""
        if not self.config.enabled:
            return
        
        connection_id = str(id(dbapi_connection))
        
        with self._lock:
            if connection_id in self._connections:
                self._connections[connection_id].is_active = False
                self._metrics["current_connections"] = len(
                    [c for c in self._connections.values() if c.is_active]
                )
    
    def _handle_checkout(self, dbapi_connection: Any, connection_record: Any, connection_proxy: Any) -> None:
        """Handle connection checkout from pool."""
        if not self.config.enabled:
            return
        
        connection_id = str(id(dbapi_connection))
        
        with self._lock:
            if connection_id in self._connections:
                self._connections[connection_id].is_active = True
    
    def _handle_checkin(self, dbapi_connection: Any, connection_record: Any) -> None:
        """Handle connection checkin to pool."""
        if not self.config.enabled:
            return
        
        connection_id = str(id(dbapi_connection))
        
        with self._lock:
            if connection_id in self._connections:
                self._connections[connection_id].is_active = False
    
    def _trigger_alert(self, alert_type: str, message: str, severity: str = "warning", **kwargs: Any) -> None:
        """Trigger an alert."""
        alert = {
            "type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > 100:  # Keep last 100 alerts
                self._alerts = self._alerts[-100:]
        
        # Log the alert
        if severity == "error":
            logger.error(f"ALERT: {message}")
        elif severity == "warning":
            logger.warning(f"ALERT: {message}")
        else:
            logger.info(f"ALERT: {message}")
    
    def check_health(self) -> DatabaseHealth:
        """
        Perform a health check on the database.
        
        Returns:
            DatabaseHealth object with current health status.
        """
        start_time = time.time()
        
        try:
            # Test database connection
            with self.engine.connect() as conn:
                # Execute a simple query
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
                
                # Get connection count
                connection_count = len(self._connections)
                active_connection_count = len(
                    [c for c in self._connections.values() if c.is_active]
                )
                
                # Calculate response time
                response_time = time.time() - start_time
                
                # Determine status
                if response_time > 1.0:  # More than 1 second
                    status = "degraded"
                elif self._metrics["total_errors"] > 0:
                    status = "degraded"
                elif self._metrics["total_slow_queries"] > 10:
                    status = "degraded"
                else:
                    status = "healthy"
                
                self._health = DatabaseHealth(
                    status=status,
                    last_check=datetime.now(),
                    response_time=response_time,
                    connection_count=connection_count,
                    active_connection_count=active_connection_count,
                    error_count=self._metrics["total_errors"],
                    slow_query_count=self._metrics["total_slow_queries"],
                    long_running_query_count=self._metrics["total_long_running_queries"],
                )
                
                return self._health
                
        except Exception as e:
            self._health = DatabaseHealth(
                status="unhealthy",
                last_check=datetime.now(),
                response_time=time.time() - start_time,
                error_count=self._metrics["total_errors"] + 1,
                slow_query_count=self._metrics["total_slow_queries"],
                long_running_query_count=self._metrics["total_long_running_queries"],
            )
            
            if self.config.alert_on_connection_issues:
                self._trigger_alert(
                    "health_check_failed",
                    f"Database health check failed: {e}",
                    severity="error"
                )
            
            return self._health
    
    def start_health_monitoring(self) -> None:
        """Start periodic health monitoring."""
        if not self.config.enabled:
            return
        
        def health_check_loop():
            while True:
                self.check_health()
                time.sleep(self.config.health_check_interval)
        
        # Start health check thread
        health_thread = threading.Thread(target=health_check_loop, daemon=True)
        health_thread.start()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current monitoring metrics."""
        with self._lock:
            metrics = self._metrics.copy()
            
            # Add calculated metrics
            metrics["avg_execution_time"] = (
                metrics["total_execution_time"] / metrics["total_queries"] 
                if metrics["total_queries"] > 0 else 0
            )
            
            metrics["queries_per_second"] = (
                metrics["total_queries"] / max(metrics["total_execution_time"], 0.001)
                if metrics["total_execution_time"] > 0 else 0
            )
            
            return metrics
    
    def get_query_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent query history."""
        with self._lock:
            return [q.to_dict() for q in self._query_history[-limit:]]
    
    def get_slow_queries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get slow queries."""
        with self._lock:
            return [q.to_dict() for q in self._slow_queries[-limit:]]
    
    def get_long_running_queries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get long-running queries."""
        with self._lock:
            return [q.to_dict() for q in self._long_running_queries[-limit:]]
    
    def get_connection_info(self) -> List[Dict[str, Any]]:
        """Get connection information."""
        with self._lock:
            return [c.to_dict() for c in self._connections.values()]
    
    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self._lock:
            return self._alerts[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of database monitoring data."""
        return {
            "health": self._health.to_dict(),
            "metrics": self.get_metrics(),
            "config": self.config.to_dict(),
            "last_health_check": self._last_health_check.isoformat(),
        }
    
    def reset(self) -> None:
        """Reset monitoring data."""
        with self._lock:
            self._query_history.clear()
            self._slow_queries.clear()
            self._long_running_queries.clear()
            self._connections.clear()
            self._alerts.clear()
            
            self._metrics = {
                "total_queries": 0,
                "total_execution_time": 0.0,
                "total_errors": 0,
                "total_slow_queries": 0,
                "total_long_running_queries": 0,
                "peak_connections": 0,
                "current_connections": 0,
            }
            
            self._slow_query_count = 0
    
    def enable(self) -> None:
        """Enable monitoring."""
        self.config.enabled = True
    
    def disable(self) -> None:
        """Disable monitoring."""
        self.config.enabled = False


# =============================================================================
# Query Timer Context Manager
# =============================================================================

@contextmanager
def query_timer(monitor: DatabaseMonitor, query_name: str = "unnamed"):
    """
    Context manager for timing database queries.
    
    Args:
        monitor: DatabaseMonitor instance.
        query_name: Name for the query (for identification).
        
    Yields:
        None
    """
    start_time = time.time()
    try:
        yield
    finally:
        execution_time = time.time() - start_time
        
        # Record the query
        query = QueryInfo(
            query=query_name,
            execution_time=execution_time,
            start_time=datetime.now() - timedelta(seconds=execution_time),
            end_time=datetime.now(),
            success=True,
        )
        
        with monitor._lock:
            monitor._query_history.append(query)
            if len(monitor._query_history) > monitor.config.max_query_history:
                monitor._query_history = monitor._query_history[-monitor.config.max_query_history:]
            
            if query.is_slow:
                monitor._slow_queries.append(query)
                if len(monitor._slow_queries) > monitor.config.max_slow_queries:
                    monitor._slow_queries = monitor._slow_queries[-monitor.config.max_slow_queries:]


# =============================================================================
# Global Database Monitor
# =============================================================================

# Global monitor instance (will be initialized when engine is available)
_database_monitor: Optional[DatabaseMonitor] = None


def get_database_monitor() -> Optional[DatabaseMonitor]:
    """Get the global database monitor instance."""
    return _database_monitor


def init_database_monitor(engine: Engine, config: Optional[MonitoringConfig] = None) -> DatabaseMonitor:
    """
    Initialize the global database monitor.
    
    Args:
        engine: SQLAlchemy engine to monitor.
        config: Monitoring configuration.
        
    Returns:
        DatabaseMonitor instance.
    """
    global _database_monitor
    _database_monitor = DatabaseMonitor(engine, config)
    return _database_monitor


# =============================================================================
# Utility Functions
# =============================================================================

def format_query_stats(stats: Dict[str, Any]) -> str:
    """Format query statistics as a human-readable string."""
    lines = [
        f"Total Queries: {stats.get('total_queries', 0)}",
        f"Total Execution Time: {stats.get('total_execution_time', 0):.3f}s",
        f"Average Execution Time: {stats.get('avg_execution_time', 0):.3f}s",
        f"Queries per Second: {stats.get('queries_per_second', 0):.2f}",
        f"Total Errors: {stats.get('total_errors', 0)}",
        f"Slow Queries: {stats.get('total_slow_queries', 0)}",
        f"Long Running Queries: {stats.get('total_long_running_queries', 0)}",
        f"Peak Connections: {stats.get('peak_connections', 0)}",
        f"Current Connections: {stats.get('current_connections', 0)}",
    ]
    return "\n".join(lines)


def format_health_status(health: Dict[str, Any]) -> str:
    """Format health status as a human-readable string."""
    status_emoji = {
        "healthy": "✅",
        "degraded": "⚠️",
        "unhealthy": "❌"
    }
    
    emoji = status_emoji.get(health.get("status", "unknown"), "❓")
    
    lines = [
        f"Status: {emoji} {health.get('status', 'unknown')}",
        f"Last Check: {health.get('last_check', 'N/A')}",
        f"Response Time: {health.get('response_time', 0):.3f}s",
        f"Connections: {health.get('connection_count', 0)} ({health.get('active_connection_count', 0)} active)",
        f"Errors: {health.get('error_count', 0)}",
        f"Slow Queries: {health.get('slow_query_count', 0)}",
        f"Long Running Queries: {health.get('long_running_query_count', 0)}",
    ]
    
    return "\n".join(lines)


__all__ = [
    # Configuration
    'MonitoringConfig', 'DEFAULT_MONITORING_CONFIG',
    
    # Data classes
    'QueryInfo', 'ConnectionInfo', 'DatabaseHealth',
    
    # Main classes
    'DatabaseMonitor',
    
    # Context managers
    'query_timer',
    
    # Global functions
    'get_database_monitor', 'init_database_monitor',
    
    # Utility functions
    'format_query_stats', 'format_health_status',
]
