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
Queue System for Open Omniscience

This module provides a SQLite-based task queue for processing jobs.
It's designed as a lightweight alternative to Celery/Redis for environments
where those services are not available.

Features:
- SQLite-based persistent queue
- Priority-based task ordering
- Task retries with exponential backoff
- Worker pool management
- Progress tracking

Author: Ideotion
"""

import sys
import time
import logging
import sqlite3
import threading
import queue
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid
import json

# Configure logging
from src.utils.logging_config import setup_logging
logger = setup_logging("queue")


class TaskStatus(Enum):
    """Status of a task in the queue."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority levels for tasks."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Task:
    """Represents a task in the queue."""
    task_id: str
    task_type: str
    payload: Dict
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    result: Optional[Dict] = None
    worker_id: Optional[str] = None
    
    @property
    def is_completed(self) -> bool:
        """Check if task is completed."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    
    @property
    def is_runnable(self) -> bool:
        """Check if task can be run."""
        return self.status == TaskStatus.PENDING
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "result": self.result,
            "worker_id": self.worker_id
        }
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Task":
        """Create Task from database row."""
        return cls(
            task_id=row["task_id"],
            task_type=row["task_type"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            error_message=row["error_message"],
            result=json.loads(row["result"]) if row["result"] else None,
            worker_id=row["worker_id"]
        )


class TaskQueue:
    """
    SQLite-based task queue.
    
    This provides a persistent, lightweight alternative to Celery/Redis
    for environments where those services are not available.
    """
    
    DEFAULT_DB_PATH = "data/queue.db"
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the task queue.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.repo_root = Path(__file__).parent.parent.parent.resolve()
        
        if db_path is None:
            db_path = self.repo_root / self.DEFAULT_DB_PATH
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        # In-memory queue for pending tasks
        self._pending_queue = queue.PriorityQueue()
        self._lock = threading.Lock()
        
        # Load pending tasks into memory
        self._load_pending_tasks()
        
        logger.info(f"TaskQueue initialized at {self.db_path}")
    
    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    error_message TEXT,
                    result TEXT,
                    worker_id TEXT
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
            
            conn.commit()
    
    def _load_pending_tasks(self):
        """Load pending tasks from database into memory queue."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM tasks 
                WHERE status = 'pending' 
                ORDER BY priority DESC, created_at ASC
            """)
            
            for row in cursor.fetchall():
                task = Task.from_row(row)
                # Use negative priority for PriorityQueue (lower number = higher priority)
                self._pending_queue.put((-task.priority.value, task.created_at, task))
    
    def _save_task(self, task: Task):
        """Save a task to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tasks (
                    task_id, task_type, payload, priority, status, 
                    created_at, started_at, completed_at, retry_count, 
                    max_retries, error_message, result, worker_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.task_type,
                json.dumps(task.payload),
                task.priority.value,
                task.status.value,
                task.created_at.isoformat(),
                task.started_at.isoformat() if task.started_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                task.retry_count,
                task.max_retries,
                task.error_message,
                json.dumps(task.result) if task.result else None,
                task.worker_id
            ))
            conn.commit()
    
    def _delete_task(self, task_id: str):
        """Delete a task from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()
    
    def add_task(
        self,
        task_type: str,
        payload: Dict,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3
    ) -> Task:
        """
        Add a new task to the queue.
        
        Args:
            task_type: Type of task (e.g., "scrape", "process", "analyze").
            payload: Task payload as dictionary.
            priority: Task priority.
            max_retries: Maximum number of retry attempts.
            
        Returns:
            The created Task object.
        """
        task = Task(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            payload=payload,
            priority=priority,
            max_retries=max_retries
        )
        
        # Save to database
        self._save_task(task)
        
        # Add to in-memory queue
        with self._lock:
            self._pending_queue.put((-priority.value, task.created_at, task))
        
        logger.debug(f"Added task {task.task_id} of type {task_type} with priority {priority.value}")
        return task
    
    def add_tasks(self, tasks: List[Tuple[str, Dict, TaskPriority]]) -> List[Task]:
        """
        Add multiple tasks to the queue.
        
        Args:
            tasks: List of tuples (task_type, payload, priority).
            
        Returns:
            List of created Task objects.
        """
        created_tasks = []
        for task_type, payload, priority in tasks:
            task = self.add_task(task_type, payload, priority)
            created_tasks.append(task)
        return created_tasks
    
    def get_next_task(self, worker_id: str = None) -> Optional[Task]:
        """
        Get the next task to process.
        
        Args:
            worker_id: ID of the worker requesting the task.
            
        Returns:
            Task if available, None otherwise.
        """
        with self._lock:
            if self._pending_queue.empty():
                return None
            
            # Get highest priority task (lowest number in priority queue)
            _, _, task = self._pending_queue.get()
            
            # Update task status
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            task.worker_id = worker_id
            task.retry_count = 0
            
            # Save to database
            self._save_task(task)
            
            return task
    
    def complete_task(self, task_id: str, result: Dict = None) -> bool:
        """
        Mark a task as completed.
        
        Args:
            task_id: ID of the task.
            result: Result of task execution.
            
        Returns:
            True if task was updated, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            task = Task.from_row(row)
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc)
            task.result = result
            
            self._save_task(task)
            logger.debug(f"Completed task {task_id}")
            return True
    
    def fail_task(self, task_id: str, error_message: str) -> bool:
        """
        Mark a task as failed.
        
        Args:
            task_id: ID of the task.
            error_message: Error message.
            
        Returns:
            True if task was updated, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            task = Task.from_row(row)
            task.retry_count += 1
            task.error_message = error_message
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                # Re-queue the task
                task.status = TaskStatus.PENDING
                task.started_at = None
                task.worker_id = None
                
                # Add back to queue
                with self._lock:
                    self._pending_queue.put((-task.priority.value, task.created_at, task))
            else:
                # Mark as failed
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc)
            
            self._save_task(task)
            
            if task.status == TaskStatus.FAILED:
                logger.warning(f"Task {task_id} failed after {task.retry_count} retries: {error_message}")
            else:
                logger.debug(f"Task {task_id} retry #{task.retry_count}")
            
            return True
    
    def retry_task(self, task_id: str) -> bool:
        """
        Manually retry a failed task.
        
        Args:
            task_id: ID of the task.
            
        Returns:
            True if task was reset, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            task = Task.from_row(row)
            task.status = TaskStatus.PENDING
            task.started_at = None
            task.completed_at = None
            task.worker_id = None
            task.retry_count = 0
            task.error_message = None
            
            # Add back to queue
            with self._lock:
                self._pending_queue.put((-task.priority.value, task.created_at, task))
            
            self._save_task(task)
            logger.info(f"Retrying task {task_id}")
            return True
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending or running task.
        
        Args:
            task_id: ID of the task.
            
        Returns:
            True if task was cancelled, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            task = Task.from_row(row)
            if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return False
            
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)
            
            self._save_task(task)
            logger.info(f"Cancelled task {task_id}")
            return True
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get a task by ID.
        
        Args:
            task_id: ID of the task.
            
        Returns:
            Task if found, None otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return Task.from_row(row)
    
    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """
        Get all tasks with a specific status.
        
        Args:
            status: Status to filter by.
            
        Returns:
            List of Task objects.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status.value,)
            )
            return [Task.from_row(row) for row in cursor.fetchall()]
    
    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        return self.get_tasks_by_status(TaskStatus.PENDING)
    
    def get_running_tasks(self) -> List[Task]:
        """Get all running tasks."""
        return self.get_tasks_by_status(TaskStatus.RUNNING)
    
    def get_completed_tasks(self, limit: int = 100) -> List[Task]:
        """
        Get completed tasks.
        
        Args:
            limit: Maximum number of tasks to return.
            
        Returns:
            List of Task objects.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM tasks 
                WHERE status IN ('completed', 'failed', 'cancelled') 
                ORDER BY completed_at DESC 
                LIMIT ?
            """, (limit,))
            return [Task.from_row(row) for row in cursor.fetchall()]
    
    def get_task_count_by_status(self) -> Dict[str, int]:
        """
        Get count of tasks by status.
        
        Returns:
            Dictionary mapping status to count.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM tasks 
                GROUP BY status
            """)
            return {row["status"]: row["count"] for row in cursor.fetchall()}
    
    def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """
        Remove completed tasks older than specified age.
        
        Args:
            max_age_hours: Maximum age in hours.
            
        Returns:
            Number of tasks deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM tasks 
                WHERE status IN ('completed', 'failed', 'cancelled') 
                AND completed_at < ?
            """, (cutoff.isoformat(),))
            deleted_count = cursor.rowcount
            conn.commit()
        
        logger.info(f"Cleaned up {deleted_count} completed tasks older than {max_age_hours} hours")
        return deleted_count
    
    def clear_all_tasks(self) -> int:
        """
        Clear all tasks from the queue.
        
        Returns:
            Number of tasks deleted.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM tasks")
            deleted_count = cursor.rowcount
            conn.commit()
        
        # Clear in-memory queue
        with self._lock:
            while not self._pending_queue.empty():
                self._pending_queue.get()
        
        logger.info(f"Cleared {deleted_count} tasks")
        return deleted_count
    
    def get_stats(self) -> Dict:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue statistics.
        """
        counts = self.get_task_count_by_status()
        
        # Get queue size from memory
        with self._lock:
            queue_size = self._pending_queue.qsize()
        
        return {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "queue_size": queue_size,
            "total": sum(counts.values())
        }


class QueueWorker:
    """
    Worker that processes tasks from the queue.
    
    This worker runs in a separate thread and continuously processes
    tasks from the queue until stopped.
    """
    
    def __init__(
        self,
        worker_id: str,
        task_queue: TaskQueue,
        task_handlers: Dict[str, Callable[[Dict], Dict]],
        poll_interval: float = 1.0
    ):
        """
        Initialize the worker.
        
        Args:
            worker_id: Unique ID for this worker.
            task_queue: TaskQueue instance.
            task_handlers: Dictionary mapping task types to handler functions.
            poll_interval: Seconds between queue polls.
        """
        self.worker_id = worker_id
        self.task_queue = task_queue
        self.task_handlers = task_handlers
        self.poll_interval = poll_interval
        self._running = False
        self._thread = None
        
        logger.info(f"Worker {worker_id} initialized")
    
    def _process_task(self, task: Task) -> bool:
        """
        Process a single task.
        
        Args:
            task: Task to process.
            
        Returns:
            True if task was processed successfully, False otherwise.
        """
        handler = self.task_handlers.get(task.task_type)
        if not handler:
            error_msg = f"No handler for task type: {task.task_type}"
            self.task_queue.fail_task(task.task_id, error_msg)
            return False
        
        try:
            logger.debug(f"Worker {self.worker_id} processing task {task.task_id} ({task.task_type})")
            
            # Execute the handler
            result = handler(task.payload)
            
            # Mark as completed
            self.task_queue.complete_task(task.task_id, result)
            return True
            
        except Exception as e:
            error_msg = f"Error processing task: {str(e)}"
            self.task_queue.fail_task(task.task_id, error_msg)
            return False
    
    def _run(self):
        """Main worker loop."""
        logger.info(f"Worker {self.worker_id} started")
        
        while self._running:
            try:
                # Get next task
                task = self.task_queue.get_next_task(self.worker_id)
                
                if task:
                    self._process_task(task)
                else:
                    # No tasks available, wait and retry
                    time.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")
                time.sleep(self.poll_interval)
        
        logger.info(f"Worker {self.worker_id} stopped")
    
    def start(self):
        """Start the worker thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop the worker thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


class QueueManager:
    """
    Manager for the task queue and worker pool.
    
    This provides a high-level interface for managing the queue system.
    """
    
    def __init__(
        self,
        num_workers: int = 5,
        db_path: Optional[str] = None,
        poll_interval: float = 1.0
    ):
        """
        Initialize the queue manager.
        
        Args:
            num_workers: Number of worker threads.
            db_path: Path to SQLite database.
            poll_interval: Seconds between queue polls.
        """
        self.task_queue = TaskQueue(db_path)
        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self._workers: List[QueueWorker] = []
        self._task_handlers: Dict[str, Callable] = {}
        self._running = False
    
    def register_handler(self, task_type: str, handler: Callable[[Dict], Dict]):
        """
        Register a task handler.
        
        Args:
            task_type: Type of task.
            handler: Function to handle the task.
        """
        self._task_handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type}")
    
    def start(self):
        """Start the queue manager and all workers."""
        if self._running:
            return
        
        self._running = True
        
        # Create workers
        for i in range(self.num_workers):
            worker = QueueWorker(
                worker_id=f"worker_{i}",
                task_queue=self.task_queue,
                task_handlers=self._task_handlers,
                poll_interval=self.poll_interval
            )
            worker.start()
            self._workers.append(worker)
        
        logger.info(f"QueueManager started with {self.num_workers} workers")
    
    def stop(self):
        """Stop the queue manager and all workers."""
        if not self._running:
            return
        
        self._running = False
        
        for worker in self._workers:
            worker.stop()
        
        self._workers.clear()
        logger.info("QueueManager stopped")
    
    def add_task(
        self,
        task_type: str,
        payload: Dict,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3
    ) -> Task:
        """
        Add a task to the queue.
        
        Args:
            task_type: Type of task.
            payload: Task payload.
            priority: Task priority.
            max_retries: Maximum retries.
            
        Returns:
            The created Task.
        """
        return self.task_queue.add_task(task_type, payload, priority, max_retries)
    
    def get_stats(self) -> Dict:
        """Get queue statistics."""
        return self.task_queue.get_stats()
    
    def cleanup(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed tasks.
        
        Args:
            max_age_hours: Maximum age in hours.
            
        Returns:
            Number of tasks deleted.
        """
        return self.task_queue.cleanup_completed_tasks(max_age_hours)


if __name__ == "__main__":
    # Example usage
    import time
    
    # Define a simple task handler
    def scrape_handler(payload: Dict) -> Dict:
        """Example scrape task handler."""
        print(f"Scraping: {payload.get('url', 'unknown')}")
        time.sleep(1)  # Simulate work
        return {"status": "completed", "url": payload.get("url")}
    
    def process_handler(payload: Dict) -> Dict:
        """Example process task handler."""
        print(f"Processing: {payload.get('title', 'unknown')}")
        time.sleep(0.5)
        return {"status": "completed", "title": payload.get("title")}
    
    # Create and start queue manager
    manager = QueueManager(num_workers=3)
    manager.register_handler("scrape", scrape_handler)
    manager.register_handler("process", process_handler)
    manager.start()
    
    try:
        # Add some tasks
        for i in range(10):
            manager.add_task(
                task_type="scrape",
                payload={"url": f"https://example.com/page{i}"},
                priority=TaskPriority.HIGH if i % 2 == 0 else TaskPriority.NORMAL
            )
        
        for i in range(5):
            manager.add_task(
                task_type="process",
                payload={"title": f"Article {i}"},
                priority=TaskPriority.LOW
            )
        
        # Wait for tasks to complete
        while True:
            stats = manager.get_stats()
            print(f"\rQueue stats: Pending={stats['pending']}, Running={stats['running']}, "
                  f"Completed={stats['completed']}, Failed={stats['failed']}", end="")
            
            if stats['pending'] == 0 and stats['running'] == 0:
                print("\nAll tasks completed!")
                break
            
            time.sleep(1)
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        manager.stop()
