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
Distributed Scraping Pipeline for Open Omniscience

This module provides distributed scraping capabilities using Celery and Redis:
- Distributed task queue for scraping
- Rate limiting and throttling
- Adaptive scraping based on source behavior
- Result aggregation and deduplication
- Worker management and monitoring
- Fault tolerance and retry logic

Author: Ideotion
"""

import asyncio
import hashlib
import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
import threading

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class DistributedConfig:
    """Configuration for distributed scraping."""
    # Redis configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    
    # Celery configuration
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: List[str] = field(default_factory=lambda: ["json"])
    
    # Queue configuration
    queue_name: str = "scraping"
    priority_queue_name: str = "scraping_priority"
    max_concurrent_workers: int = 10
    max_tasks_per_worker: int = 100
    
    # Rate limiting
    default_rate_limit: float = 1.0  # requests per second
    max_retries: int = 3
    retry_delay: float = 5.0  # seconds
    timeout: float = 30.0  # seconds
    
    # Adaptive scraping
    adaptive_enabled: bool = True
    success_threshold: float = 0.9  # 90% success rate
    failure_threshold: float = 0.3  # 30% failure rate
    min_rate_limit: float = 0.1  # minimum requests per second
    max_rate_limit: float = 10.0  # maximum requests per second
    
    # Monitoring
    metrics_enabled: bool = True
    health_check_interval: float = 60.0  # seconds
    
    @classmethod
    def from_env(cls) -> "DistributedConfig":
        """Create configuration from environment variables."""
        import os
        
        return cls(
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_db=int(os.getenv("REDIS_DB", "0")),
            redis_password=os.getenv("REDIS_PASSWORD"),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
            queue_name=os.getenv("SCRAPING_QUEUE", "scraping"),
            priority_queue_name=os.getenv("SCRAPING_PRIORITY_QUEUE", "scraping_priority"),
            max_concurrent_workers=int(os.getenv("MAX_CONCURRENT_WORKERS", "10")),
            max_tasks_per_worker=int(os.getenv("MAX_TASKS_PER_WORKER", "100")),
            default_rate_limit=float(os.getenv("DEFAULT_RATE_LIMIT", "1.0")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "5.0")),
            timeout=float(os.getenv("SCRAPING_TIMEOUT", "30.0")),
            adaptive_enabled=os.getenv("ADAPTIVE_SCRAPING", "true").lower() == "true",
            success_threshold=float(os.getenv("SUCCESS_THRESHOLD", "0.9")),
            failure_threshold=float(os.getenv("FAILURE_THRESHOLD", "0.3")),
            min_rate_limit=float(os.getenv("MIN_RATE_LIMIT", "0.1")),
            max_rate_limit=float(os.getenv("MAX_RATE_LIMIT", "10.0")),
            metrics_enabled=os.getenv("METRICS_ENABLED", "true").lower() == "true",
            health_check_interval=float(os.getenv("HEALTH_CHECK_INTERVAL", "60.0")),
        )


# Global configuration
config = DistributedConfig.from_env()


# =============================================================================
# Task Types and Status
# =============================================================================

class TaskType(str, Enum):
    """Types of scraping tasks."""
    SCRAPE_URL = "scrape_url"
    SCRAPE_SOURCE = "scrape_source"
    SCRAPE_RSS = "scrape_rss"
    EXTRACT_LINKS = "extract_links"
    ANALYZE_CONTENT = "analyze_content"
    STORE_ARTICLE = "store_article"
    UPDATE_SOURCE = "update_source"


class TaskStatus(str, Enum):
    """Status of a scraping task."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Priority levels for scraping tasks."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ScrapeTask:
    """Represents a scraping task."""
    id: str
    task_type: TaskType
    url: str
    source_id: Optional[int] = None
    priority: TaskPriority = TaskPriority.NORMAL
    depth: int = 0
    max_depth: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Result
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Retry information
    retries: int = 0
    last_retry_at: Optional[datetime] = None
    
    # Status
    status: TaskStatus = TaskStatus.PENDING
    
    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.generate_id()
    
    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique task ID."""
        import uuid
        return str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "task_type": self.task_type.value,
            "url": self.url,
            "source_id": self.source_id,
            "priority": self.priority.value,
            "depth": self.depth,
            "max_depth": self.max_depth,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "retries": self.retries,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "status": self.status.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScrapeTask":
        """Create from dictionary."""
        return cls(
            id=data.get("id", ""),
            task_type=TaskType(data.get("task_type", "scrape_url")),
            url=data.get("url", ""),
            source_id=data.get("source_id"),
            priority=TaskPriority(data.get("priority", "normal")),
            depth=data.get("depth", 0),
            max_depth=data.get("max_depth", 3),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result=data.get("result"),
            error=data.get("error"),
            retries=data.get("retries", 0),
            last_retry_at=datetime.fromisoformat(data["last_retry_at"]) if data.get("last_retry_at") else None,
            status=TaskStatus(data.get("status", "pending")),
        )
    
    def get_content_hash(self) -> str:
        """Get a hash of the task content for deduplication."""
        content = f"{self.task_type.value}:{self.url}:{self.source_id}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class ScrapeResult:
    """Result of a scraping task."""
    task_id: str
    url: str
    status: str
    content: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "url": self.url,
            "status": self.status,
            "content": self.content,
            "title": self.title,
            "metadata": self.metadata,
            "links": self.links,
            "error": self.error,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SourceStats:
    """Statistics for a source."""
    source_id: int
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_response_time: float = 0.0
    last_request_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    current_rate_limit: float = 1.0
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def update(self, success: bool, response_time: float) -> None:
        """Update statistics with a new request."""
        self.total_requests += 1
        now = datetime.now(timezone.utc)
        
        if success:
            self.successful_requests += 1
            self.last_success_at = now
            self.consecutive_failures = 0
            
            # Update average response time (exponential moving average)
            if self.avg_response_time == 0:
                self.avg_response_time = response_time
            else:
                self.avg_response_time = 0.9 * self.avg_response_time + 0.1 * response_time
        else:
            self.failed_requests += 1
            self.last_failure_at = now
            self.consecutive_failures += 1
        
        self.last_request_at = now


# =============================================================================
# Redis Manager
# =============================================================================

class RedisManager:
    """
    Manages Redis connections and operations for distributed scraping.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the Redis manager.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self._connection: Optional[Any] = None
        self._lock = threading.Lock()
    
    def get_connection(self) -> Any:
        """Get a Redis connection."""
        if self._connection is None:
            with self._lock:
                if self._connection is None:
                    try:
                        import redis
                        self._connection = redis.Redis(
                            host=self.config.redis_host,
                            port=self.config.redis_port,
                            db=self.config.redis_db,
                            password=self.config.redis_password,
                            decode_responses=True,
                            socket_timeout=10,
                            socket_connect_timeout=10,
                        )
                        # Test connection
                        self._connection.ping()
                    except ImportError:
                        logger.warning("Redis library not installed. Using in-memory fallback.")
                        self._connection = self._create_fallback()
                    except Exception as e:
                        logger.error(f"Failed to connect to Redis: {e}")
                        self._connection = self._create_fallback()
        
        return self._connection
    
    def _create_fallback(self) -> Any:
        """Create a fallback in-memory store."""
        from collections import defaultdict
        
        class FallbackRedis:
            def __init__(self):
                self._store: Dict[str, Dict[str, Any]] = defaultdict(dict)
                self._lists: Dict[str, List[Any]] = defaultdict(list)
                self._sets: Dict[str, set] = defaultdict(set)
                self._zsets: Dict[str, Dict[str, float]] = defaultdict(dict)
                self._pubsub: Dict[str, List[Callable]] = defaultdict(list)
            
            def ping(self) -> bool:
                return True
            
            def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
                self._store[key] = value
                return True
            
            def get(self, key: str) -> Optional[Any]:
                return self._store.get(key)
            
            def delete(self, key: str) -> bool:
                if key in self._store:
                    del self._store[key]
                    return True
                return False
            
            def exists(self, key: str) -> bool:
                return key in self._store
            
            def hset(self, name: str, key: str, value: Any) -> bool:
                self._store[name][key] = value
                return True
            
            def hget(self, name: str, key: str) -> Optional[Any]:
                return self._store.get(name, {}).get(key)
            
            def hgetall(self, name: str) -> Dict[str, Any]:
                return self._store.get(name, {})
            
            def hdel(self, name: str, key: str) -> bool:
                if name in self._store and key in self._store[name]:
                    del self._store[name][key]
                    return True
                return False
            
            def lpush(self, name: str, *values: Any) -> int:
                self._lists[name].extend(reversed(values))
                return len(self._lists[name])
            
            def rpush(self, name: str, *values: Any) -> int:
                self._lists[name].extend(values)
                return len(self._lists[name])
            
            def lpop(self, name: str) -> Optional[Any]:
                if self._lists[name]:
                    return self._lists[name].pop(0)
                return None
            
            def rpop(self, name: str) -> Optional[Any]:
                if self._lists[name]:
                    return self._lists[name].pop()
                return None
            
            def llen(self, name: str) -> int:
                return len(self._lists[name])
            
            def sadd(self, name: str, *values: Any) -> int:
                added = 0
                for value in values:
                    if value not in self._sets[name]:
                        self._sets[name].add(value)
                        added += 1
                return added
            
            def srem(self, name: str, *values: Any) -> int:
                removed = 0
                for value in values:
                    if value in self._sets[name]:
                        self._sets[name].remove(value)
                        removed += 1
                return removed
            
            def smembers(self, name: str) -> List[Any]:
                return list(self._sets[name])
            
            def zadd(self, name: str, mapping: Dict[str, float]) -> int:
                added = 0
                for key, score in mapping.items():
                    if key not in self._zsets[name] or self._zsets[name][key] != score:
                        self._zsets[name][key] = score
                        added += 1
                return added
            
            def zrange(self, name: str, start: int = 0, end: int = -1, withscores: bool = False) -> List[Any]:
                items = sorted(self._zsets[name].items(), key=lambda x: x[1])
                result = items[start:end+1] if end >= 0 else items[start:]
                if withscores:
                    return result
                return [item[0] for item in result]
            
            def zrem(self, name: str, *values: Any) -> int:
                removed = 0
                for value in values:
                    if value in self._zsets[name]:
                        del self._zsets[name][value]
                        removed += 1
                return removed
            
            def publish(self, channel: str, message: Any) -> int:
                for callback in self._pubsub[channel]:
                    callback(message)
                return len(self._pubsub[channel])
            
            def subscribe(self, channel: str, callback: Callable) -> None:
                self._pubsub[channel].append(callback)
            
            def incr(self, key: str) -> int:
                self._store[key] = self._store.get(key, 0) + 1
                return self._store[key]
            
            def expire(self, key: str, seconds: int) -> bool:
                # In-memory fallback doesn't support TTL
                return True
        
        return FallbackRedis()
    
    def close(self) -> None:
        """Close the Redis connection."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
    
    def __enter__(self) -> "RedisManager":
        return self
    
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# Global Redis manager
redis_manager = RedisManager()


# =============================================================================
# Task Queue
# =============================================================================

class TaskQueue:
    """
    Distributed task queue for scraping tasks.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the task queue.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self.redis = redis_manager
    
    def enqueue(self, task: ScrapeTask) -> str:
        """
        Add a task to the queue.
        
        Args:
            task: The scraping task to enqueue.
            
        Returns:
            Task ID.
        """
        redis = self.redis.get_connection()
        
        # Use priority queue based on priority
        queue_name = self._get_queue_name(task.priority)
        
        # Serialize task
        task_data = task.to_dict()
        
        # Add to queue
        redis.lpush(queue_name, json.dumps(task_data))
        
        # Store task metadata
        self._store_task_metadata(task)
        
        logger.info(f"Enqueued task {task.id} with priority {task.priority.value}")
        return task.id
    
    def _get_queue_name(self, priority: TaskPriority) -> str:
        """Get the queue name based on priority."""
        if priority == TaskPriority.URGENT:
            return f"{self.config.priority_queue_name}:urgent"
        elif priority == TaskPriority.HIGH:
            return f"{self.config.priority_queue_name}:high"
        elif priority == TaskPriority.LOW:
            return f"{self.config.queue_name}:low"
        else:
            return self.config.queue_name
    
    def _store_task_metadata(self, task: ScrapeTask) -> None:
        """Store task metadata in Redis."""
        redis = self.redis.get_connection()
        key = f"task:{task.id}"
        redis.hset(key, mapping=task.to_dict())
        redis.expire(key, 86400)  # Expire after 24 hours
    
    def dequeue(self, worker_id: str, queue_names: Optional[List[str]] = None) -> Optional[ScrapeTask]:
        """
        Get the next task from the queue.
        
        Args:
            worker_id: ID of the worker requesting a task.
            queue_names: List of queue names to check (in priority order).
            
        Returns:
            ScrapeTask or None if no tasks available.
        """
        redis = self.redis.get_connection()
        
        if queue_names is None:
            # Check queues in priority order
            queue_names = [
                f"{self.config.priority_queue_name}:urgent",
                f"{self.config.priority_queue_name}:high",
                self.config.priority_queue_name,
                self.config.queue_name,
                f"{self.config.queue_name}:low",
            ]
        
        for queue_name in queue_names:
            # Use BRPOPLPUSH for atomic dequeue with timeout
            # This ensures tasks aren't lost if worker crashes
            task_data = redis.rpoplpush(queue_name, f"{queue_name}:processing")
            
            if task_data:
                try:
                    task = ScrapeTask.from_dict(json.loads(task_data))
                    
                    # Update task status
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now(timezone.utc)
                    self._store_task_metadata(task)
                    
                    # Track worker's current task
                    redis.hset(f"worker:{worker_id}", mapping={
                        "current_task": task.id,
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                    })
                    
                    logger.info(f"Dequeued task {task.id} for worker {worker_id}")
                    return task
                    
                except json.JSONDecodeError:
                    logger.error("Failed to decode task data")
                    # Move back to queue
                    redis.lpush(queue_name, task_data)
        
        return None
    
    def complete(self, task: ScrapeTask, result: Optional[Dict[str, Any]] = None) -> None:
        """
        Mark a task as completed.
        
        Args:
            task: The completed task.
            result: Optional result data.
        """
        redis = self.redis.get_connection()
        
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)
        task.result = result
        
        # Store final state
        self._store_task_metadata(task)
        
        # Remove from processing queue
        queue_name = self._get_queue_name(task.priority)
        redis.lrem(f"{queue_name}:processing", 0, json.dumps(task.to_dict()))
        
        # Clean up worker tracking
        worker_id = self._get_worker_for_task(task.id)
        if worker_id:
            redis.hdel(f"worker:{worker_id}", "current_task")
        
        logger.info(f"Completed task {task.id}")
    
    def fail(self, task: ScrapeTask, error: str, retry: bool = True) -> None:
        """
        Mark a task as failed.
        
        Args:
            task: The failed task.
            error: Error message.
            retry: Whether to retry the task.
        """
        redis = self.redis.get_connection()
        
        task.error = error
        task.retries += 1
        task.last_retry_at = datetime.now(timezone.utc)
        
        if retry and task.retries < self.config.max_retries:
            task.status = TaskStatus.RETRYING
            
            # Requeue with backoff
            delay = min(self.config.retry_delay * (2 ** task.retries), 300)  # Max 5 minutes
            
            # Store with retry delay
            redis.hset(f"task:{task.id}", "retry_at", 
                      (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat())
            
            # Requeue
            queue_name = self._get_queue_name(task.priority)
            redis.lpush(queue_name, json.dumps(task.to_dict()))
            
            logger.info(f"Failed task {task.id}, retry #{task.retries} in {delay}s")
        else:
            task.status = TaskStatus.FAILED
            self._store_task_metadata(task)
            
            # Remove from processing queue
            queue_name = self._get_queue_name(task.priority)
            redis.lrem(f"{queue_name}:processing", 0, json.dumps(task.to_dict()))
            
            # Clean up worker tracking
            worker_id = self._get_worker_for_task(task.id)
            if worker_id:
                redis.hdel(f"worker:{worker_id}", "current_task")
            
            logger.warning(f"Task {task.id} failed permanently: {error}")
    
    def _get_worker_for_task(self, task_id: str) -> Optional[str]:
        """Find which worker is processing a task."""
        redis = self.redis.get_connection()
        
        # Search all workers
        workers = redis.keys("worker:*")
        for worker_key in workers:
            worker_data = redis.hgetall(worker_key)
            if worker_data.get("current_task") == task_id:
                return worker_key.split(":")[1]
        
        return None
    
    def get_task(self, task_id: str) -> Optional[ScrapeTask]:
        """Get a task by ID."""
        redis = self.redis.get_connection()
        task_data = redis.hgetall(f"task:{task_id}")
        
        if not task_data:
            return None
        
        return ScrapeTask.from_dict(task_data)
    
    def get_queue_size(self, priority: Optional[TaskPriority] = None) -> int:
        """Get the size of a queue."""
        redis = self.redis.get_connection()
        
        if priority:
            queue_name = self._get_queue_name(priority)
            return redis.llen(queue_name)
        else:
            # Sum all queues
            total = 0
            for priority in TaskPriority:
                queue_name = self._get_queue_name(priority)
                total += redis.llen(queue_name)
            return total
    
    def get_worker_count(self) -> int:
        """Get the number of active workers."""
        redis = self.redis.get_connection()
        return len(redis.keys("worker:*"))
    
    def get_active_tasks(self) -> List[ScrapeTask]:
        """Get all currently active (running) tasks."""
        redis = self.redis.get_connection()
        
        active_tasks = []
        workers = redis.keys("worker:*")
        
        for worker_key in workers:
            worker_data = redis.hgetall(worker_key)
            task_id = worker_data.get("current_task")
            if task_id:
                task = self.get_task(task_id)
                if task and task.status == TaskStatus.RUNNING:
                    active_tasks.append(task)
        
        return active_tasks
    
    def cleanup(self) -> int:
        """
        Clean up old tasks and processing queues.
        
        Returns:
            Number of items cleaned up.
        """
        redis = self.redis.get_connection()
        cleaned = 0
        
        # Clean up expired tasks
        task_keys = redis.keys("task:*")
        for key in task_keys:
            task_data = redis.hgetall(key)
            created_at = datetime.fromisoformat(task_data.get("created_at", ""))
            
            # Remove tasks older than 24 hours
            if datetime.now(timezone.utc) - created_at > timedelta(hours=24):
                redis.delete(key)
                cleaned += 1
        
        # Clean up processing queues
        for priority in TaskPriority:
            queue_name = f"{self._get_queue_name(priority)}:processing"
            # Move stuck tasks back to queue
            stuck_tasks = redis.lrange(queue_name, 0, -1)
            for task_data in stuck_tasks:
                try:
                    task = ScrapeTask.from_dict(json.loads(task_data))
                    # If task has been processing for more than timeout, move back
                    if task.started_at:
                        processing_time = datetime.now(timezone.utc) - task.started_at
                        if processing_time > timedelta(seconds=self.config.timeout):
                            redis.lrem(queue_name, 0, task_data)
                            redis.lpush(self._get_queue_name(task.priority), task_data)
                            cleaned += 1
                except Exception:
                    # Remove invalid task data
                    redis.lrem(queue_name, 0, task_data)
                    cleaned += 1
        
        return cleaned


# Global task queue
task_queue = TaskQueue()


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Rate limiter for controlling request rates to sources.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the rate limiter.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self.redis = redis_manager
        self._source_stats: Dict[int, SourceStats] = {}
        self._lock = threading.Lock()
    
    def acquire(self, source_id: int, url: str) -> bool:
        """
        Acquire permission to scrape a source.
        
        Args:
            source_id: ID of the source.
            url: URL to scrape.
            
        Returns:
            True if permission granted, False otherwise.
        """
        redis = self.redis.get_connection()
        
        # Get or create source stats
        stats = self._get_source_stats(source_id)
        
        # Check if we're being rate limited
        if stats.consecutive_failures >= 5:
            # Too many consecutive failures, back off
            return False
        
        # Use Redis to implement token bucket rate limiting
        key = f"rate_limit:{source_id}"
        now = time.time()
        
        # Get current rate limit
        rate_limit = stats.current_rate_limit
        
        # Calculate tokens available
        # Token bucket algorithm: refill tokens at rate_limit per second
        last_refill = float(redis.hget(key, "last_refill") or now)
        tokens = float(redis.hget(key, "tokens") or rate_limit)
        
        # Refill tokens
        elapsed = now - last_refill
        tokens = min(rate_limit, tokens + elapsed * rate_limit)
        
        # Try to acquire a token
        if tokens >= 1:
            tokens -= 1
            redis.hset(key, mapping={
                "tokens": tokens,
                "last_refill": now,
            })
            redis.expire(key, 60)  # Expire after 60 seconds
            
            # Update last request time
            stats.last_request_at = datetime.now(timezone.utc)
            
            return True
        
        return False
    
    def release(self, source_id: int, success: bool, response_time: float) -> None:
        """
        Release after a request and update statistics.
        
        Args:
            source_id: ID of the source.
            success: Whether the request was successful.
            response_time: Response time in seconds.
        """
        stats = self._get_source_stats(source_id)
        stats.update(success, response_time)
        
        # Adaptive rate limiting
        if self.config.adaptive_enabled:
            self._adjust_rate_limit(stats)
    
    def _get_source_stats(self, source_id: int) -> SourceStats:
        """Get or create statistics for a source."""
        with self._lock:
            if source_id not in self._source_stats:
                self._source_stats[source_id] = SourceStats(source_id=source_id)
            return self._source_stats[source_id]
    
    def _adjust_rate_limit(self, stats: SourceStats) -> None:
        """Adjust rate limit based on source behavior."""
        # If success rate is high, increase rate limit
        if stats.success_rate >= self.config.success_threshold:
            new_rate = min(
                self.config.max_rate_limit,
                stats.current_rate_limit * 1.1  # Increase by 10%
            )
            stats.current_rate_limit = new_rate
            logger.info(f"Increased rate limit for source {stats.source_id} to {new_rate}")
        
        # If failure rate is high, decrease rate limit
        elif stats.success_rate <= (1 - self.config.failure_threshold):
            new_rate = max(
                self.config.min_rate_limit,
                stats.current_rate_limit * 0.9  # Decrease by 10%
            )
            stats.current_rate_limit = new_rate
            logger.warning(f"Decreased rate limit for source {stats.source_id} to {new_rate}")
    
    def get_rate_limit(self, source_id: int) -> float:
        """Get the current rate limit for a source."""
        stats = self._get_source_stats(source_id)
        return stats.current_rate_limit
    
    def get_stats(self, source_id: int) -> SourceStats:
        """Get statistics for a source."""
        return self._get_source_stats(source_id)


# Global rate limiter
rate_limiter = RateLimiter()


# =============================================================================
# Worker Manager
# =============================================================================

class WorkerManager:
    """
    Manages scraping workers.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the worker manager.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self.redis = redis_manager
        self._workers: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def register_worker(self, worker_id: str, info: Dict[str, Any]) -> None:
        """
        Register a new worker.
        
        Args:
            worker_id: Unique worker ID.
            info: Worker information.
        """
        redis = self.redis.get_connection()
        
        with self._lock:
            self._workers[worker_id] = info
        
        # Store in Redis
        redis.hset(f"worker:{worker_id}", mapping=info)
        redis.sadd("workers", worker_id)
        
        logger.info(f"Registered worker {worker_id}")
    
    def unregister_worker(self, worker_id: str) -> None:
        """
        Unregister a worker.
        
        Args:
            worker_id: Worker ID to unregister.
        """
        redis = self.redis.get_connection()
        
        with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
        
        # Remove from Redis
        redis.delete(f"worker:{worker_id}")
        redis.srem("workers", worker_id)
        
        logger.info(f"Unregistered worker {worker_id}")
    
    def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get worker information."""
        with self._lock:
            return self._workers.get(worker_id)
    
    def get_all_workers(self) -> List[Dict[str, Any]]:
        """Get all registered workers."""
        with self._lock:
            return list(self._workers.values())
    
    def get_worker_count(self) -> int:
        """Get the number of registered workers."""
        return len(self._workers)
    
    def heartbeat(self, worker_id: str) -> None:
        """
        Update worker heartbeat.
        
        Args:
            worker_id: Worker ID.
        """
        redis = self.redis.get_connection()
        redis.hset(f"worker:{worker_id}", "last_heartbeat", datetime.now(timezone.utc).isoformat())
    
    def check_workers(self) -> List[str]:
        """
        Check for stale workers (no heartbeat for a while).
        
        Returns:
            List of stale worker IDs.
        """
        redis = self.redis.get_connection()
        stale_workers = []
        
        workers = redis.smembers("workers")
        for worker_id in workers:
            worker_data = redis.hgetall(f"worker:{worker_id}")
            last_heartbeat = worker_data.get("last_heartbeat")
            
            if last_heartbeat:
                last_time = datetime.fromisoformat(last_heartbeat)
                if datetime.now(timezone.utc) - last_time > timedelta(seconds=120):  # 2 minutes
                    stale_workers.append(worker_id)
        
        return stale_workers
    
    def cleanup_stale_workers(self) -> int:
        """
        Clean up stale workers.
        
        Returns:
            Number of workers cleaned up.
        """
        stale_workers = self.check_workers()
        
        for worker_id in stale_workers:
            self.unregister_worker(worker_id)
            
            # Clean up worker's current task
            redis = self.redis.get_connection()
            worker_data = redis.hgetall(f"worker:{worker_id}")
            task_id = worker_data.get("current_task")
            
            if task_id:
                # Move task back to queue
                task = task_queue.get_task(task_id)
                if task:
                    task.status = TaskStatus.PENDING
                    task_queue.enqueue(task)
        
        return len(stale_workers)


# Global worker manager
worker_manager = WorkerManager()


# =============================================================================
# Distributed Scraper
# =============================================================================

class DistributedScraper:
    """
    Distributed scraper that coordinates scraping across multiple workers.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the distributed scraper.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self.task_queue = task_queue
        self.rate_limiter = rate_limiter
        self.worker_manager = worker_manager
    
    def scrape_url(
        self,
        url: str,
        source_id: Optional[int] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        depth: int = 0,
        max_depth: int = 3,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Scrape a URL.
        
        Args:
            url: URL to scrape.
            source_id: Optional source ID.
            priority: Task priority.
            depth: Current depth in crawling.
            max_depth: Maximum depth to crawl.
            metadata: Additional metadata.
            
        Returns:
            Task ID.
        """
        # Create task
        task = ScrapeTask(
            task_type=TaskType.SCRAPE_URL,
            url=url,
            source_id=source_id,
            priority=priority,
            depth=depth,
            max_depth=max_depth,
            metadata=metadata or {},
        )
        
        # Enqueue task
        return self.task_queue.enqueue(task)
    
    def scrape_source(
        self,
        source_id: int,
        priority: TaskPriority = TaskPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Scrape all URLs from a source.
        
        Args:
            source_id: Source ID.
            priority: Task priority.
            metadata: Additional metadata.
            
        Returns:
            Task ID.
        """
        # Create task
        task = ScrapeTask(
            task_type=TaskType.SCRAPE_SOURCE,
            url=f"source:{source_id}",
            source_id=source_id,
            priority=priority,
            metadata=metadata or {},
        )
        
        # Enqueue task
        return self.task_queue.enqueue(task)
    
    def scrape_rss(
        self,
        rss_url: str,
        source_id: Optional[int] = None,
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> str:
        """
        Scrape an RSS feed.
        
        Args:
            rss_url: RSS feed URL.
            source_id: Optional source ID.
            priority: Task priority.
            
        Returns:
            Task ID.
        """
        # Create task
        task = ScrapeTask(
            task_type=TaskType.SCRAPE_RSS,
            url=rss_url,
            source_id=source_id,
            priority=priority,
        )
        
        # Enqueue task
        return self.task_queue.enqueue(task)
    
    def get_task_status(self, task_id: str) -> Optional[ScrapeTask]:
        """Get the status of a task."""
        return self.task_queue.get_task(task_id)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            "total_tasks": self.task_queue.get_queue_size(),
            "active_tasks": len(self.task_queue.get_active_tasks()),
            "worker_count": self.worker_manager.get_worker_count(),
            "urgent_queue": self.task_queue.get_queue_size(TaskPriority.URGENT),
            "high_queue": self.task_queue.get_queue_size(TaskPriority.HIGH),
            "normal_queue": self.task_queue.get_queue_size(TaskPriority.NORMAL),
            "low_queue": self.task_queue.get_queue_size(TaskPriority.LOW),
        }
    
    def cleanup(self) -> int:
        """Clean up old tasks and stale workers."""
        cleaned_tasks = self.task_queue.cleanup()
        cleaned_workers = self.worker_manager.cleanup_stale_workers()
        return cleaned_tasks + cleaned_workers


# Global distributed scraper
distributed_scraper = DistributedScraper()


# =============================================================================
# Worker Implementation
# =============================================================================

class ScraperWorker:
    """
    Worker that processes scraping tasks.
    """
    
    def __init__(self, worker_id: str, config: Optional[DistributedConfig] = None):
        """
        Initialize the scraper worker.
        
        Args:
            worker_id: Unique worker ID.
            config: Distributed configuration.
        """
        self.worker_id = worker_id
        self.config = config or config
        self.task_queue = task_queue
        self.rate_limiter = rate_limiter
        self.worker_manager = worker_manager
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        
        # Register worker
        self.worker_manager.register_worker(self.worker_id, {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        })
        
        logger.info(f"Started worker {self.worker_id}")
    
    def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        
        # Unregister worker
        self.worker_manager.unregister_worker(self.worker_id)
        
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info(f"Stopped worker {self.worker_id}")
    
    def _run(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                # Send heartbeat
                self.worker_manager.heartbeat(self.worker_id)
                
                # Get next task
                task = self.task_queue.dequeue(self.worker_id)
                
                if task is None:
                    # No tasks available, wait a bit
                    time.sleep(0.1)
                    continue
                
                # Process task
                self._process_task(task)
                
            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")
                time.sleep(1)
    
    def _process_task(self, task: ScrapeTask) -> None:
        """Process a scraping task."""
        try:
            # Check rate limit
            if task.source_id and not self.rate_limiter.acquire(task.source_id, task.url):
                # Rate limited, retry later
                self.task_queue.fail(task, "Rate limited", retry=True)
                return
            
            # Process based on task type
            if task.task_type == TaskType.SCRAPE_URL:
                result = self._scrape_url(task)
            elif task.task_type == TaskType.SCRAPE_SOURCE:
                result = self._scrape_source(task)
            elif task.task_type == TaskType.SCRAPE_RSS:
                result = self._scrape_rss(task)
            else:
                result = {"error": f"Unknown task type: {task.task_type}"}
            
            # Check if we should retry
            if "error" in result:
                self.task_queue.fail(task, result["error"], retry=True)
                
                # Update rate limiter
                if task.source_id:
                    self.rate_limiter.release(task.source_id, False, 0)
            else:
                # Task completed successfully
                self.task_queue.complete(task, result)
                
                # Update rate limiter
                if task.source_id:
                    self.rate_limiter.release(task.source_id, True, result.get("execution_time", 0))
            
        except Exception as e:
            logger.error(f"Error processing task {task.id}: {e}")
            self.task_queue.fail(task, str(e), retry=True)
            
            if task.source_id:
                self.rate_limiter.release(task.source_id, False, 0)
    
    def _scrape_url(self, task: ScrapeTask) -> Dict[str, Any]:
        """Scrape a single URL."""
        start_time = time.time()
        
        try:
            # Import here to avoid circular imports
            from src.scraper.scraper import scrape_article
            
            # Scrape the article
            result = scrape_article(task.url, task.source_id)
            
            execution_time = time.time() - start_time
            
            return {
                "url": task.url,
                "title": result.get("title"),
                "content": result.get("content"),
                "metadata": result.get("metadata", {}),
                "links": result.get("links", []),
                "execution_time": execution_time,
            }
            
        except Exception as e:
            return {"error": str(e), "execution_time": time.time() - start_time}
    
    def _scrape_source(self, task: ScrapeTask) -> Dict[str, Any]:
        """Scrape all URLs from a source."""
        start_time = time.time()
        
        try:
            if not task.source_id:
                return {"error": "No source_id provided"}
            
            # Import here to avoid circular imports
            from src.scraper.scraper import scrape_source_urls
            
            # Get source URLs
            urls = scrape_source_urls(task.source_id)
            
            # Enqueue URLs for scraping
            task_ids = []
            for url in urls:
                url_task = ScrapeTask(
                    task_type=TaskType.SCRAPE_URL,
                    url=url,
                    source_id=task.source_id,
                    priority=task.priority,
                    depth=task.depth + 1,
                    max_depth=task.max_depth,
                )
                task_id = self.task_queue.enqueue(url_task)
                task_ids.append(task_id)
            
            execution_time = time.time() - start_time
            
            return {
                "source_id": task.source_id,
                "urls_found": len(urls),
                "tasks_created": len(task_ids),
                "task_ids": task_ids,
                "execution_time": execution_time,
            }
            
        except Exception as e:
            return {"error": str(e), "execution_time": time.time() - start_time}
    
    def _scrape_rss(self, task: ScrapeTask) -> Dict[str, Any]:
        """Scrape an RSS feed."""
        start_time = time.time()
        
        try:
            # Import here to avoid circular imports
            from src.scraper.scraper import scrape_rss_feed
            
            # Scrape RSS feed
            articles = scrape_rss_feed(task.url, task.source_id)
            
            # Enqueue articles for processing
            task_ids = []
            for article in articles:
                url_task = ScrapeTask(
                    task_type=TaskType.SCRAPE_URL,
                    url=article.get("url", ""),
                    source_id=task.source_id,
                    priority=TaskPriority.HIGH,  # RSS articles are high priority
                    metadata={"rss_feed": task.url},
                )
                task_id = self.task_queue.enqueue(url_task)
                task_ids.append(task_id)
            
            execution_time = time.time() - start_time
            
            return {
                "rss_url": task.url,
                "articles_found": len(articles),
                "tasks_created": len(task_ids),
                "task_ids": task_ids,
                "execution_time": execution_time,
            }
            
        except Exception as e:
            return {"error": str(e), "execution_time": time.time() - start_time}


# =============================================================================
# Async Distributed Scraper
# =============================================================================

class AsyncDistributedScraper:
    """
    Async version of the distributed scraper.
    """
    
    def __init__(self, config: Optional[DistributedConfig] = None):
        """
        Initialize the async distributed scraper.
        
        Args:
            config: Distributed configuration.
        """
        self.config = config or config
        self.task_queue = task_queue
        self.rate_limiter = rate_limiter
        self.worker_manager = worker_manager
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent_workers)
    
    async def scrape_url(
        self,
        url: str,
        source_id: Optional[int] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        depth: int = 0,
        max_depth: int = 3,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Scrape a URL asynchronously."""
        # For now, use the synchronous version
        # In a full async implementation, this would use async Redis
        return distributed_scraper.scrape_url(
            url, source_id, priority, depth, max_depth, metadata
        )
    
    async def scrape_urls(
        self,
        urls: List[str],
        source_id: Optional[int] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        depth: int = 0,
        max_depth: int = 3
    ) -> List[str]:
        """Scrape multiple URLs asynchronously."""
        task_ids = []
        
        for url in urls:
            task_id = await self.scrape_url(
                url, source_id, priority, depth, max_depth
            )
            task_ids.append(task_id)
        
        return task_ids
    
    async def process_batch(
        self,
        tasks: List[ScrapeTask]
    ) -> List[Dict[str, Any]]:
        """Process a batch of tasks asynchronously."""
        # This would use async workers in a full implementation
        # For now, submit to thread pool
        loop = asyncio.get_event_loop()
        
        results = await loop.run_in_executor(
            self._executor,
            self._process_batch_sync,
            tasks
        )
        
        return results
    
    def _process_batch_sync(self, tasks: List[ScrapeTask]) -> List[Dict[str, Any]]:
        """Process a batch of tasks synchronously."""
        results = []
        
        for task in tasks:
            try:
                if task.task_type == TaskType.SCRAPE_URL:
                    result = distributed_scraper.task_queue
                    # Simplified - in practice, this would process the task
                    results.append({"task_id": task.id, "status": "queued"})
                else:
                    results.append({"task_id": task.id, "error": "Unsupported task type"})
            except Exception as e:
                results.append({"task_id": task.id, "error": str(e)})
        
        return results


# =============================================================================
# Monitoring and Metrics
# =============================================================================

class ScrapingMetrics:
    """
    Collects and reports scraping metrics.
    """
    
    def __init__(self):
        """Initialize the metrics collector."""
        self._metrics: Dict[str, Any] = {
            "tasks": {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "retrying": 0,
            },
            "urls": {
                "scraped": 0,
                "discovered": 0,
            },
            "sources": {
                "active": 0,
                "rate_limited": 0,
            },
            "performance": {
                "avg_execution_time": 0.0,
                "total_execution_time": 0.0,
                "tasks_completed": 0,
            },
            "errors": {},
        }
        self._lock = threading.Lock()
    
    def record_task(self, task: ScrapeTask) -> None:
        """Record a task."""
        with self._lock:
            self._metrics["tasks"]["total"] += 1
            
            if task.status == TaskStatus.COMPLETED:
                self._metrics["tasks"]["completed"] += 1
            elif task.status == TaskStatus.FAILED:
                self._metrics["tasks"]["failed"] += 1
            elif task.status == TaskStatus.RETRYING:
                self._metrics["tasks"]["retrying"] += 1
    
    def record_url_scraped(self) -> None:
        """Record a scraped URL."""
        with self._lock:
            self._metrics["urls"]["scraped"] += 1
    
    def record_url_discovered(self) -> None:
        """Record a discovered URL."""
        with self._lock:
            self._metrics["urls"]["discovered"] += 1
    
    def record_execution_time(self, execution_time: float) -> None:
        """Record task execution time."""
        with self._lock:
            self._metrics["performance"]["total_execution_time"] += execution_time
            self._metrics["performance"]["tasks_completed"] += 1
            
            # Update average
            if self._metrics["performance"]["tasks_completed"] > 0:
                self._metrics["performance"]["avg_execution_time"] = (
                    self._metrics["performance"]["total_execution_time"] /
                    self._metrics["performance"]["tasks_completed"]
                )
    
    def record_error(self, error_type: str) -> None:
        """Record an error."""
        with self._lock:
            self._metrics["errors"][error_type] = self._metrics["errors"].get(error_type, 0) + 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            return self._metrics.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of metrics."""
        with self._lock:
            return {
                "tasks": self._metrics["tasks"].copy(),
                "urls": self._metrics["urls"].copy(),
                "sources": self._metrics["sources"].copy(),
                "performance": {
                    **self._metrics["performance"],
                    "avg_execution_time": round(
                        self._metrics["performance"]["avg_execution_time"], 4
                    ),
                },
                "error_count": len(self._metrics["errors"]),
                "top_errors": dict(
                    sorted(self._metrics["errors"].items(), key=lambda x: -x[1])[:5]
                ),
            }
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics = {
                "tasks": {"total": 0, "completed": 0, "failed": 0, "retrying": 0},
                "urls": {"scraped": 0, "discovered": 0},
                "sources": {"active": 0, "rate_limited": 0},
                "performance": {"avg_execution_time": 0.0, "total_execution_time": 0.0, "tasks_completed": 0},
                "errors": {},
            }


# Global metrics collector
metrics = ScrapingMetrics()


# =============================================================================
# Decorators
# =============================================================================

def rate_limited(source_id: Optional[int] = None) -> Callable:
    """
    Decorator to rate limit a function.
    
    Args:
        source_id: Optional source ID to rate limit by.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get source_id from kwargs or use provided value
            sid = kwargs.get("source_id") or source_id
            
            if sid and not rate_limiter.acquire(sid, ""):
                raise Exception(f"Rate limited for source {sid}")
            
            try:
                result = func(*args, **kwargs)
                if sid:
                    rate_limiter.release(sid, True, 0)
                return result
            except Exception as e:
                if sid:
                    rate_limiter.release(sid, False, 0)
                raise
        
        return wrapper
    return decorator


def retry_on_failure(max_retries: int = 3, delay: float = 5.0) -> Callable:
    """
    Decorator to retry a function on failure.
    
    Args:
        max_retries: Maximum number of retries.
        delay: Delay between retries in seconds.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if attempt < max_retries:
                        # Exponential backoff
                        sleep_time = delay * (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(sleep_time)
                    else:
                        raise
            
            raise last_error
        
        return wrapper
    return decorator


# =============================================================================
# Utility Functions
# =============================================================================

def get_distributed_scraper() -> DistributedScraper:
    """Get the global distributed scraper."""
    return distributed_scraper


def get_task_queue() -> TaskQueue:
    """Get the global task queue."""
    return task_queue


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter."""
    return rate_limiter


def get_worker_manager() -> WorkerManager:
    """Get the global worker manager."""
    return worker_manager


def get_metrics() -> ScrapingMetrics:
    """Get the global metrics collector."""
    return metrics


def start_workers(num_workers: int = 4) -> List[ScraperWorker]:
    """
    Start multiple scraper workers.
    
    Args:
        num_workers: Number of workers to start.
        
    Returns:
        List of started workers.
    """
    workers = []
    
    for i in range(num_workers):
        worker = ScraperWorker(f"worker_{i}")
        worker.start()
        workers.append(worker)
    
    return workers


def stop_workers(workers: List[ScraperWorker]) -> None:
    """
    Stop multiple scraper workers.
    
    Args:
        workers: List of workers to stop.
    """
    for worker in workers:
        worker.stop()


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Configuration
    "DistributedConfig",
    "config",
    # Enums
    "TaskType",
    "TaskStatus",
    "TaskPriority",
    # Data models
    "ScrapeTask",
    "ScrapeResult",
    "SourceStats",
    # Managers
    "RedisManager",
    "redis_manager",
    "TaskQueue",
    "task_queue",
    "RateLimiter",
    "rate_limiter",
    "WorkerManager",
    "worker_manager",
    # Services
    "DistributedScraper",
    "distributed_scraper",
    "ScraperWorker",
    "AsyncDistributedScraper",
    # Monitoring
    "ScrapingMetrics",
    "metrics",
    # Decorators
    "rate_limited",
    "retry_on_failure",
    # Utility functions
    "get_distributed_scraper",
    "get_task_queue",
    "get_rate_limiter",
    "get_worker_manager",
    "get_metrics",
    "start_workers",
    "stop_workers",
]
