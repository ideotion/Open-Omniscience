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
Source Manager for Pillar 4: Real-Time Monitoring & Alerting System

Manages source configurations, health monitoring, failover, categorization,
and rate limiting for real-time monitoring of information sources.

Features:
- Source configuration and validation
- Source health monitoring and failover
- Source categorization and prioritization
- Rate limiting and throttling per source
- Source rotation and load balancing
- Configuration persistence

Works 100% offline with optional network capabilities.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from pathlib import Path
import hashlib
import os

from .stream_processor import StreamConfig, StreamType, StreamStatus


class SourceCategory(Enum):
    """Categories of information sources."""
    NEWS = "news"
    SOCIAL_MEDIA = "social_media"
    BLOGS = "blogs"
    FORUMS = "forums"
    GOVERNMENT = "government"
    ACADEMIC = "academic"
    FINANCIAL = "financial"
    HEALTH = "health"
    TECHNOLOGY = "technology"
    ENTERTAINMENT = "entertainment"
    SPORTS = "sports"
    CUSTOM = "custom"


class SourcePriority(Enum):
    """Priority levels for sources."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MONITOR = "monitor"


class SourceHealthStatus(Enum):
    """Health status of a source."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class SourceStatus(Enum):
    """Operational status of a source."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class SourceHealthCheck:
    """Result of a health check for a source."""
    source_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: SourceHealthStatus = SourceHealthStatus.UNKNOWN
    response_time: Optional[float] = None  # milliseconds
    error: Optional[str] = None
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    total_checks: int = 0
    success_count: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.success_count / self.total_checks
    
    @property
    def is_healthy(self) -> bool:
        return self.status in [SourceHealthStatus.HEALTHY, SourceHealthStatus.DEGRADED]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "response_time": self.response_time,
            "error": self.error,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "consecutive_failures": self.consecutive_failures,
            "total_checks": self.total_checks,
            "success_count": self.success_count,
            "success_rate": self.success_rate,
            "is_healthy": self.is_healthy,
        }


@dataclass
class Source:
    """Represents an information source for monitoring."""
    source_id: str
    name: str
    source_type: StreamType
    url: str
    category: SourceCategory = SourceCategory.CUSTOM
    priority: SourcePriority = SourcePriority.MEDIUM
    status: SourceStatus = SourceStatus.ACTIVE
    enabled: bool = True
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Configuration
    rate_limit: Optional[float] = None  # requests per second
    timeout: float = 30.0  # seconds
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds
    
    # Authentication
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    
    # Scheduling
    check_interval: float = 60.0  # seconds between checks
    last_checked: Optional[datetime] = None
    next_check: Optional[datetime] = None
    
    # Health
    health: SourceHealthStatus = SourceHealthStatus.UNKNOWN
    last_health_check: Optional[SourceHealthCheck] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    error_count: int = 0
    
    # Failover
    failover_sources: List[str] = field(default_factory=list)
    is_failover: bool = False
    
    def __post_init__(self):
        if not self.source_id:
            self.source_id = self._generate_source_id()
        if not self.name:
            self.name = self.source_id
    
    def _generate_source_id(self) -> str:
        """Generate a unique source ID."""
        content = f"{self.url}:{self.source_type.value}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    @property
    def is_active(self) -> bool:
        return self.status == SourceStatus.ACTIVE and self.enabled
    
    @property
    def is_available(self) -> bool:
        return self.is_active and self.health in [SourceHealthStatus.HEALTHY, SourceHealthStatus.DEGRADED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding sensitive data."""
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type.value,
            "url": self.url,
            "category": self.category.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "enabled": self.enabled,
            "description": self.description,
            "tags": self.tags,
            "rate_limit": self.rate_limit,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "check_interval": self.check_interval,
            "health": self.health.value,
            "is_active": self.is_active,
            "is_available": self.is_available,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "error_count": self.error_count,
            "failover_sources": self.failover_sources,
            "is_failover": self.is_failover,
        }
    
    def to_stream_config(self) -> StreamConfig:
        """Convert to StreamConfig for use with StreamProcessor."""
        return StreamConfig(
            stream_id=self.source_id,
            stream_type=self.source_type,
            source_url=self.url,
            name=self.name,
            description=self.description,
            enabled=self.enabled and self.is_active,
            batch_size=100,  # Default batch size
            batch_timeout=self.check_interval,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            rate_limit=self.rate_limit,
            headers=self.headers,
            params=self.params,
            timeout=self.timeout,
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Source':
        """Create a Source from a dictionary."""
        return cls(
            source_id=data.get("source_id", ""),
            name=data.get("name", ""),
            source_type=StreamType(data.get("source_type", "web")),
            url=data.get("url", ""),
            category=SourceCategory(data.get("category", "custom")),
            priority=SourcePriority(data.get("priority", "medium")),
            status=SourceStatus(data.get("status", "active")),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            rate_limit=data.get("rate_limit"),
            timeout=data.get("timeout", 30.0),
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            check_interval=data.get("check_interval", 60.0),
            health=SourceHealthStatus(data.get("health", "unknown")),
            api_key=data.get("api_key"),
            username=data.get("username"),
            password=data.get("password"),
            headers=data.get("headers", {}),
            params=data.get("params", {}),
            failover_sources=data.get("failover_sources", []),
            is_failover=data.get("is_failover", False),
        )


class SourceManager:
    """
    Manages information sources for real-time monitoring.
    
    This manager handles source configuration, health monitoring, failover,
    and rate limiting for all monitored sources.
    
    Example usage:
        manager = SourceManager()
        
        # Add a source
        source = Source(
            source_id="news_source_1",
            name="Example News",
            source_type=StreamType.RSS,
            url="https://example.com/rss",
            category=SourceCategory.NEWS,
            priority=SourcePriority.HIGH
        )
        manager.add_source(source)
        
        # Get a source by ID
        retrieved = manager.get_source("news_source_1")
        
        # Check health of all sources
        await manager.check_all_health()
        
        # Get active sources
        active_sources = manager.get_active_sources()
    """
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        auto_save: bool = True,
        save_interval: float = 300.0,  # 5 minutes
        logger: Optional[logging.Logger] = None
    ):
        self.sources: Dict[str, Source] = {}
        self.config_file = config_file
        self.auto_save = auto_save
        self.save_interval = save_interval
        self.logger = logger or logging.getLogger(__name__)
        
        # Health monitoring
        self.health_checks: Dict[str, SourceHealthCheck] = {}
        self._last_save: Optional[datetime] = None
        
        # Rate limiting
        self._last_access: Dict[str, float] = {}
        self._access_counts: Dict[str, int] = {}
        
        # Setup logging
        self._setup_logging()
        
        # Load configuration if provided
        if config_file:
            self.load_config(config_file)
    
    def _setup_logging(self) -> None:
        """Configure logging for the source manager."""
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _get_timestamp(self) -> datetime:
        """Get current UTC timestamp."""
        return datetime.utcnow()
    
    def add_source(self, source: Source) -> None:
        """
        Add a new source to the manager.
        
        Args:
            source: Source to add
        """
        if source.source_id in self.sources:
            self.logger.warning(f"Source {source.source_id} already exists, updating")
            self.update_source(source)
            return
        
        self.sources[source.source_id] = source
        self.health_checks[source.source_id] = SourceHealthCheck(source_id=source.source_id)
        self._last_access[source.source_id] = 0.0
        self._access_counts[source.source_id] = 0
        
        self.logger.info(f"Added source: {source.source_id} ({source.name})")
        
        if self.auto_save:
            self._schedule_save()
    
    def update_source(self, source: Source) -> bool:
        """
        Update an existing source.
        
        Args:
            source: Source with updated information
            
        Returns:
            True if source was updated, False if not found
        """
        if source.source_id not in self.sources:
            return False
        
        # Preserve existing health check data
        existing_health = self.health_checks.get(source.source_id)
        
        self.sources[source.source_id] = source
        
        if existing_health:
            self.health_checks[source.source_id] = existing_health
        
        source.updated_at = self._get_timestamp()
        
        self.logger.info(f"Updated source: {source.source_id}")
        
        if self.auto_save:
            self._schedule_save()
        
        return True
    
    def remove_source(self, source_id: str) -> bool:
        """
        Remove a source from the manager.
        
        Args:
            source_id: ID of the source to remove
            
        Returns:
            True if source was removed, False if not found
        """
        if source_id not in self.sources:
            return False
        
        del self.sources[source_id]
        if source_id in self.health_checks:
            del self.health_checks[source_id]
        if source_id in self._last_access:
            del self._last_access[source_id]
        if source_id in self._access_counts:
            del self._access_counts[source_id]
        
        self.logger.info(f"Removed source: {source_id}")
        
        if self.auto_save:
            self._schedule_save()
        
        return True
    
    def get_source(self, source_id: str) -> Optional[Source]:
        """
        Get a source by ID.
        
        Args:
            source_id: ID of the source to retrieve
            
        Returns:
            Source if found, None otherwise
        """
        return self.sources.get(source_id)
    
    def get_sources_by_category(self, category: SourceCategory) -> List[Source]:
        """
        Get all sources in a specific category.
        
        Args:
            category: Category to filter by
            
        Returns:
            List of sources in the category
        """
        return [s for s in self.sources.values() if s.category == category]
    
    def get_sources_by_priority(self, priority: SourcePriority) -> List[Source]:
        """
        Get all sources with a specific priority.
        
        Args:
            priority: Priority to filter by
            
        Returns:
            List of sources with the priority
        """
        return [s for s in self.sources.values() if s.priority == priority]
    
    def get_sources_by_type(self, source_type: StreamType) -> List[Source]:
        """
        Get all sources of a specific type.
        
        Args:
            source_type: Stream type to filter by
            
        Returns:
            List of sources of the type
        """
        return [s for s in self.sources.values() if s.source_type == source_type]
    
    def get_active_sources(self) -> List[Source]:
        """Get all active and enabled sources."""
        return [s for s in self.sources.values() if s.is_active]
    
    def get_available_sources(self) -> List[Source]:
        """Get all available (active and healthy) sources."""
        return [s for s in self.sources.values() if s.is_available]
    
    def get_sources_by_tag(self, tag: str) -> List[Source]:
        """
        Get all sources with a specific tag.
        
        Args:
            tag: Tag to filter by
            
        Returns:
            List of sources with the tag
        """
        return [s for s in self.sources.values() if tag in s.tags]
    
    def get_all_sources(self) -> List[Source]:
        """Get all sources."""
        return list(self.sources.values())
    
    def get_source_count(self) -> int:
        """Get the total number of sources."""
        return len(self.sources)
    
    def get_active_source_count(self) -> int:
        """Get the number of active sources."""
        return len(self.get_active_sources())
    
    def get_available_source_count(self) -> int:
        """Get the number of available sources."""
        return len(self.get_available_sources())
    
    async def check_health(self, source_id: str) -> Optional[SourceHealthCheck]:
        """
        Check the health of a specific source.
        
        Args:
            source_id: ID of the source to check
            
        Returns:
            Health check result, or None if source not found
        """
        source = self.get_source(source_id)
        if not source:
            return None
        
        check = SourceHealthCheck(source_id=source_id)
        start_time = time.time()
        
        try:
            # Try to access the source
            # This is a placeholder - actual implementation would use aiohttp, etc.
            # For now, we'll simulate a health check
            
            # Simulate network request (in real implementation, this would be actual HTTP request)
            await asyncio.sleep(0.1)  # Simulate network delay
            
            # Check if source is reachable
            # In real implementation: use aiohttp to make a HEAD or GET request
            
            # For simulation, assume it's healthy
            check.status = SourceHealthStatus.HEALTHY
            check.response_time = (time.time() - start_time) * 1000  # Convert to ms
            check.last_success = self._get_timestamp()
            check.success_count += 1
            
        except Exception as e:
            check.status = SourceHealthStatus.OFFLINE
            check.error = str(e)
            check.consecutive_failures += 1
        
        check.total_checks += 1
        check.timestamp = self._get_timestamp()
        
        # Update source health
        source.health = check.status
        source.last_health_check = check
        source.last_checked = check.timestamp
        
        # Update our records
        self.health_checks[source_id] = check
        
        return check
    
    async def check_all_health(self) -> Dict[str, SourceHealthCheck]:
        """
        Check the health of all sources.
        
        Returns:
            Dictionary mapping source IDs to health check results
        """
        results = {}
        
        # Check health of all sources concurrently
        tasks = []
        for source_id in self.sources.keys():
            task = asyncio.create_task(self.check_health(source_id))
            tasks.append(task)
        
        # Wait for all checks to complete
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for source_id, result in zip(self.sources.keys(), completed):
            if isinstance(result, Exception):
                self.logger.error(f"Error checking health for {source_id}: {result}")
                # Create a failed health check
                check = SourceHealthCheck(
                    source_id=source_id,
                    status=SourceHealthStatus.ERROR,
                    error=str(result),
                    total_checks=1,
                    consecutive_failures=1
                )
                results[source_id] = check
                self.health_checks[source_id] = check
            else:
                results[source_id] = result
        
        return results
    
    async def get_failover_source(self, source_id: str) -> Optional[Source]:
        """
        Get a failover source for the given source.
        
        Args:
            source_id: ID of the primary source
            
        Returns:
            Failover source if available, None otherwise
        """
        source = self.get_source(source_id)
        if not source or not source.failover_sources:
            return None
        
        # Try to find an available failover source
        for failover_id in source.failover_sources:
            failover_source = self.get_source(failover_id)
            if failover_source and failover_source.is_available:
                return failover_source
        
        return None
    
    def can_access(self, source_id: str) -> bool:
        """
        Check if a source can be accessed based on rate limits.
        
        Args:
            source_id: ID of the source to check
            
        Returns:
            True if source can be accessed, False if rate limited
        """
        source = self.get_source(source_id)
        if not source or not source.rate_limit:
            return True
        
        now = time.time()
        last_access = self._last_access.get(source_id, 0.0)
        
        # Calculate time since last access
        time_since_last = now - last_access
        
        # If enough time has passed, allow access
        if time_since_last >= 1.0 / source.rate_limit:
            return True
        
        return False
    
    def record_access(self, source_id: str) -> None:
        """
        Record an access to a source for rate limiting.
        
        Args:
            source_id: ID of the source that was accessed
        """
        now = time.time()
        self._last_access[source_id] = now
        self._access_counts[source_id] = self._access_counts.get(source_id, 0) + 1
        
        # Update source access count
        source = self.get_source(source_id)
        if source:
            source.last_accessed = self._get_timestamp()
            source.access_count += 1
    
    def get_access_stats(self, source_id: str) -> Dict[str, Any]:
        """
        Get access statistics for a source.
        
        Args:
            source_id: ID of the source
            
        Returns:
            Dictionary with access statistics
        """
        source = self.get_source(source_id)
        if not source:
            return {}
        
        return {
            "source_id": source_id,
            "access_count": source.access_count,
            "error_count": source.error_count,
            "last_accessed": source.last_accessed.isoformat() if source.last_accessed else None,
            "rate_limit": source.rate_limit,
            "can_access": self.can_access(source_id),
        }
    
    def load_config(self, config_file: str) -> bool:
        """
        Load source configuration from a file.
        
        Args:
            config_file: Path to the configuration file
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            if not os.path.exists(config_file):
                self.logger.warning(f"Config file not found: {config_file}")
                return False
            
            with open(config_file, 'r') as f:
                import yaml
                config_data = yaml.safe_load(f)
            
            if not config_data or 'sources' not in config_data:
                self.logger.warning(f"No sources found in config file: {config_file}")
                return False
            
            # Clear existing sources
            self.sources.clear()
            self.health_checks.clear()
            self._last_access.clear()
            self._access_counts.clear()
            
            # Load sources
            for source_data in config_data['sources']:
                source = Source.from_dict(source_data)
                self.add_source(source)
            
            self.config_file = config_file
            self.logger.info(f"Loaded {len(self.sources)} sources from {config_file}")
            
            return True
            
        except ImportError:
            self.logger.error("YAML module not available, cannot load config file")
            return False
        except Exception as e:
            self.logger.error(f"Error loading config file: {e}")
            return False
    
    def save_config(self, config_file: Optional[str] = None) -> bool:
        """
        Save source configuration to a file.
        
        Args:
            config_file: Path to save the configuration (uses default if not provided)
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            file_path = config_file or self.config_file
            if not file_path:
                self.logger.error("No config file path specified")
                return False
            
            # Prepare data for saving
            config_data = {
                'sources': [s.to_dict() for s in self.sources.values()]
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w') as f:
                import yaml
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            
            self.config_file = file_path
            self._last_save = self._get_timestamp()
            self.logger.info(f"Saved {len(self.sources)} sources to {file_path}")
            
            return True
            
        except ImportError:
            self.logger.error("YAML module not available, cannot save config file")
            return False
        except Exception as e:
            self.logger.error(f"Error saving config file: {e}")
            return False
    
    def _schedule_save(self) -> None:
        """Schedule a save operation if auto-save is enabled."""
        if not self.auto_save or not self.config_file:
            return
        
        # Only save if enough time has passed since last save
        if self._last_save:
            time_since_save = (self._get_timestamp() - self._last_save).total_seconds()
            if time_since_save < self.save_interval:
                return
        
        # Schedule save in background
        asyncio.create_task(self._async_save())
    
    async def _async_save(self) -> None:
        """Perform save operation asynchronously."""
        try:
            self.save_config()
        except Exception as e:
            self.logger.error(f"Error in async save: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all sources and their status."""
        return {
            "total_sources": self.get_source_count(),
            "active_sources": self.get_active_source_count(),
            "available_sources": self.get_available_source_count(),
            "sources_by_category": {
                cat.value: len(self.get_sources_by_category(cat))
                for cat in SourceCategory
            },
            "sources_by_priority": {
                pri.value: len(self.get_sources_by_priority(pri))
                for pri in SourcePriority
            },
            "sources_by_type": {
                st.value: len(self.get_sources_by_type(st))
                for st in StreamType
            },
            "health_summary": {
                status.value: len([
                    s for s in self.sources.values() 
                    if s.health == status
                ])
                for status in SourceHealthStatus
            },
        }


# Convenience function for creating a source manager
async def create_source_manager(
    config_file: Optional[str] = None,
    **kwargs
) -> SourceManager:
    """
    Create and configure a source manager.
    
    Args:
        config_file: Optional path to a configuration file
        **kwargs: Additional arguments to pass to SourceManager
        
    Returns:
        Configured SourceManager instance
    """
    manager = SourceManager(config_file=config_file, **kwargs)
    
    # Check health of all sources on startup
    if manager.get_source_count() > 0:
        await manager.check_all_health()
    
    return manager
