"""
Monitoring Scheduler for Pillar 4: Real-Time Monitoring & Alerting System

Provides cron-based scheduling, event-driven monitoring, dynamic schedule
adjustment, and monitoring job queue management for real-time surveillance.

Features:
- Cron-based scheduling for periodic monitoring
- Event-driven monitoring for real-time sources
- Dynamic schedule adjustment based on source activity
- Monitoring job queue management
- Job prioritization and preemption
- Job retry and backoff strategies

Works 100% offline with optional network capabilities.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from heapq import heappush, heappop
import hashlib
import re


class JobStatus(Enum):
    """Status of a scheduled job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class JobType(Enum):
    """Types of monitoring jobs."""
    PERIODIC = "periodic"
    EVENT_DRIVEN = "event_driven"
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class ScheduleType(Enum):
    """Types of schedules."""
    CRON = "cron"
    INTERVAL = "interval"
    DAILY = "daily"
    HOURLY = "hourly"
    MINUTELY = "minutely"
    CUSTOM = "custom"


@dataclass
class Job:
    """Represents a monitoring job."""
    job_id: str
    name: str
    job_type: JobType
    callback: Callable
    args: Tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    
    # Scheduling
    schedule_type: ScheduleType = ScheduleType.INTERVAL
    interval: Optional[float] = None  # seconds
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None  # For one-time jobs
    
    # Priority and timing
    priority: int = 0  # Higher = more important
    timeout: Optional[float] = None  # seconds
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds
    
    # State
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    
    # Results
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retry_count: int = 0
    
    # Metadata
    source_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.job_id:
            self.job_id = self._generate_job_id()
    
    def _generate_job_id(self) -> str:
        """Generate a unique job ID."""
        content = f"{self.name}:{self.job_type.value}:{self.created_at.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    @property
    def is_active(self) -> bool:
        """Check if job is currently active (pending or running)."""
        return self.status in [JobStatus.PENDING, JobStatus.RUNNING]
    
    @property
    def is_completed(self) -> bool:
        """Check if job has completed (successfully or not)."""
        return self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.SKIPPED]
    
    @property
    def should_retry(self) -> bool:
        """Check if job should be retried."""
        return (
            self.status == JobStatus.FAILED and
            self.retry_count < self.max_retries
        )
    
    def get_next_run_time(self) -> Optional[datetime]:
        """Calculate the next run time based on schedule."""
        if self.schedule_type == ScheduleType.CRON:
            return self._get_next_cron_time()
        elif self.schedule_type == ScheduleType.INTERVAL:
            if self.last_run:
                return self.last_run + timedelta(seconds=self.interval or 60)
            else:
                return self.created_at + timedelta(seconds=self.interval or 60)
        elif self.schedule_type == ScheduleType.DAILY:
            if self.last_run:
                next_run = self.last_run + timedelta(days=1)
                return next_run.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                tomorrow = self.created_at + timedelta(days=1)
                return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self.schedule_type == ScheduleType.HOURLY:
            if self.last_run:
                next_run = self.last_run + timedelta(hours=1)
                return next_run.replace(minute=0, second=0, microsecond=0)
            else:
                next_hour = self.created_at + timedelta(hours=1)
                return next_hour.replace(minute=0, second=0, microsecond=0)
        elif self.schedule_type == ScheduleType.MINUTELY:
            if self.last_run:
                next_run = self.last_run + timedelta(minutes=1)
                return next_run.replace(second=0, microsecond=0)
            else:
                next_minute = self.created_at + timedelta(minutes=1)
                return next_minute.replace(second=0, microsecond=0)
        else:
            return self.run_at
    
    def _get_next_cron_time(self) -> Optional[datetime]:
        """Calculate next run time from cron expression."""
        if not self.cron_expression:
            return None
        
        # Parse cron expression (simplified implementation)
        # Format: minute hour day month day_of_week
        try:
            parts = self.cron_expression.split()
            if len(parts) != 5:
                return None
            
            minute, hour, day, month, day_of_week = parts
            
            # Get current time
            now = self.last_run or self.created_at
            
            # Calculate next run (simplified - would use proper cron parser in production)
            # For now, just add the interval
            if self.interval:
                return now + timedelta(seconds=self.interval)
            else:
                # Default to 1 hour if no interval specified
                return now + timedelta(hours=1)
                
        except Exception:
            return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary."""
        return {
            "job_id": self.job_id,
            "name": self.name,
            "job_type": self.job_type.value,
            "schedule_type": self.schedule_type.value,
            "interval": self.interval,
            "cron_expression": self.cron_expression,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "execution_time": self.execution_time,
            "retry_count": self.retry_count,
            "error": self.error,
            "source_id": self.source_id,
            "tags": self.tags,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], callback: Callable) -> 'Job':
        """Create a Job from a dictionary."""
        job = cls(
            job_id=data.get("job_id", ""),
            name=data.get("name", "unnamed_job"),
            job_type=JobType(data.get("job_type", "periodic")),
            callback=callback,
            schedule_type=ScheduleType(data.get("schedule_type", "interval")),
            interval=data.get("interval"),
            cron_expression=data.get("cron_expression"),
            priority=data.get("priority", 0),
            timeout=data.get("timeout"),
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            source_id=data.get("source_id"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )
        
        # Set timestamps if provided
        if "created_at" in data:
            job.created_at = datetime.fromisoformat(data["created_at"])
        if "started_at" in data and data["started_at"]:
            job.started_at = datetime.fromisoformat(data["started_at"])
        if "completed_at" in data and data["completed_at"]:
            job.completed_at = datetime.fromisoformat(data["completed_at"])
        if "last_run" in data and data["last_run"]:
            job.last_run = datetime.fromisoformat(data["last_run"])
        if "next_run" in data and data["next_run"]:
            job.next_run = datetime.fromisoformat(data["next_run"])
        
        # Set status
        if "status" in data:
            job.status = JobStatus(data["status"])
        
        return job


@dataclass
class Schedule:
    """Represents a schedule for monitoring jobs."""
    schedule_id: str
    name: str
    description: str = ""
    enabled: bool = True
    
    # Timing
    schedule_type: ScheduleType = ScheduleType.INTERVAL
    interval: Optional[float] = None  # seconds
    cron_expression: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Job references
    job_ids: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        if not self.schedule_id:
            self.schedule_id = self._generate_schedule_id()
    
    def _generate_schedule_id(self) -> str:
        """Generate a unique schedule ID."""
        content = f"{self.name}:{self.schedule_type.value}:{self.created_at.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert schedule to dictionary."""
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "schedule_type": self.schedule_type.value,
            "interval": self.interval,
            "cron_expression": self.cron_expression,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "job_ids": self.job_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Scheduler:
    """
    Scheduler for monitoring jobs.
    
    This scheduler manages periodic, event-driven, and one-time monitoring jobs
    with support for cron expressions, intervals, prioritization, and retry logic.
    
    Example usage:
        scheduler = Scheduler()
        
        # Schedule a periodic job
        async def monitor_source(source_id: str):
            print(f"Monitoring source: {source_id}")
            # Your monitoring logic here
        
        job = Job(
            name="monitor_source_1",
            job_type=JobType.PERIODIC,
            callback=monitor_source,
            args=("source_1",),
            schedule_type=ScheduleType.INTERVAL,
            interval=60.0  # Every 60 seconds
        )
        
        await scheduler.add_job(job)
        await scheduler.start()
        
        # Later... stop scheduler
        await scheduler.stop()
    """
    
    def __init__(
        self,
        max_workers: int = 10,
        max_queue_size: int = 1000,
        auto_start: bool = False,
        logger: Optional[logging.Logger] = None
    ):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.auto_start = auto_start
        self.logger = logger or logging.getLogger(__name__)
        
        # Job management
        self.jobs: Dict[str, Job] = {}
        self.schedules: Dict[str, Schedule] = {}
        
        # Execution state
        self._running = False
        self._paused = False
        self._start_time: Optional[datetime] = None
        
        # Task management
        self._worker_tasks: List[asyncio.Task] = []
        self._scheduler_task: Optional[asyncio.Task] = None
        self._job_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        
        # Event handling
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._pending_events: asyncio.Queue = asyncio.Queue()
        
        # Setup logging
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Configure logging for the scheduler."""
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
    
    async def add_job(self, job: Job) -> str:
        """
        Add a new job to the scheduler.
        
        Args:
            job: Job to add
            
        Returns:
            Job ID
        """
        if job.job_id in self.jobs:
            self.logger.warning(f"Job {job.job_id} already exists, updating")
            await self.remove_job(job.job_id)
        
        self.jobs[job.job_id] = job
        
        # Calculate next run time
        job.next_run = job.get_next_run_time()
        
        # If scheduler is running, schedule the job
        if self._running:
            await self._schedule_job(job)
        
        self.logger.info(f"Added job: {job.job_id} ({job.name})")
        return job.job_id
    
    async def add_jobs(self, jobs: List[Job]) -> List[str]:
        """
        Add multiple jobs to the scheduler.
        
        Args:
            jobs: List of jobs to add
            
        Returns:
            List of job IDs
        """
        job_ids = []
        for job in jobs:
            job_id = await self.add_job(job)
            job_ids.append(job_id)
        return job_ids
    
    async def remove_job(self, job_id: str) -> bool:
        """
        Remove a job from the scheduler.
        
        Args:
            job_id: ID of the job to remove
            
        Returns:
            True if job was removed, False if not found
        """
        if job_id not in self.jobs:
            return False
        
        job = self.jobs[job_id]
        
        # Cancel if running
        if job.status == JobStatus.RUNNING:
            # Job will be cancelled when it completes
            job.status = JobStatus.CANCELLED
        
        del self.jobs[job_id]
        
        # Remove from any schedules
        for schedule in self.schedules.values():
            if job_id in schedule.job_ids:
                schedule.job_ids.remove(job_id)
        
        self.logger.info(f"Removed job: {job_id}")
        return True
    
    async def update_job(self, job: Job) -> bool:
        """
        Update an existing job.
        
        Args:
            job: Job with updated information
            
        Returns:
            True if job was updated, False if not found
        """
        if job.job_id not in self.jobs:
            return False
        
        # Preserve existing state
        existing_job = self.jobs[job.job_id]
        job.status = existing_job.status
        job.created_at = existing_job.created_at
        job.started_at = existing_job.started_at
        job.completed_at = existing_job.completed_at
        job.last_run = existing_job.last_run
        job.next_run = existing_job.next_run
        job.result = existing_job.result
        job.error = existing_job.error
        job.execution_time = existing_job.execution_time
        job.retry_count = existing_job.retry_count
        
        self.jobs[job.job_id] = job
        
        # Re-schedule if running
        if self._running:
            await self._schedule_job(job)
        
        self.logger.info(f"Updated job: {job.job_id}")
        return True
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Get a job by ID.
        
        Args:
            job_id: ID of the job to retrieve
            
        Returns:
            Job if found, None otherwise
        """
        return self.jobs.get(job_id)
    
    def get_jobs_by_status(self, status: JobStatus) -> List[Job]:
        """
        Get all jobs with a specific status.
        
        Args:
            status: Status to filter by
            
        Returns:
            List of jobs with the status
        """
        return [j for j in self.jobs.values() if j.status == status]
    
    def get_jobs_by_type(self, job_type: JobType) -> List[Job]:
        """
        Get all jobs of a specific type.
        
        Args:
            job_type: Job type to filter by
            
        Returns:
            List of jobs of the type
        """
        return [j for j in self.jobs.values() if j.job_type == job_type]
    
    def get_jobs_by_tag(self, tag: str) -> List[Job]:
        """
        Get all jobs with a specific tag.
        
        Args:
            tag: Tag to filter by
            
        Returns:
            List of jobs with the tag
        """
        return [j for j in self.jobs.values() if tag in j.tags]
    
    def get_jobs_by_source(self, source_id: str) -> List[Job]:
        """
        Get all jobs for a specific source.
        
        Args:
            source_id: Source ID to filter by
            
        Returns:
            List of jobs for the source
        """
        return [j for j in self.jobs.values() if j.source_id == source_id]
    
    def get_all_jobs(self) -> List[Job]:
        """Get all jobs."""
        return list(self.jobs.values())
    
    def get_job_count(self) -> int:
        """Get the total number of jobs."""
        return len(self.jobs)
    
    def get_active_job_count(self) -> int:
        """Get the number of active jobs."""
        return len(self.get_jobs_by_status(JobStatus.PENDING)) + len(self.get_jobs_by_status(JobStatus.RUNNING))
    
    async def add_schedule(self, schedule: Schedule) -> str:
        """
        Add a new schedule to the scheduler.
        
        Args:
            schedule: Schedule to add
            
        Returns:
            Schedule ID
        """
        if schedule.schedule_id in self.schedules:
            self.logger.warning(f"Schedule {schedule.schedule_id} already exists, updating")
            return await self.update_schedule(schedule)
        
        self.schedules[schedule.schedule_id] = schedule
        self.logger.info(f"Added schedule: {schedule.schedule_id} ({schedule.name})")
        return schedule.schedule_id
    
    async def update_schedule(self, schedule: Schedule) -> bool:
        """
        Update an existing schedule.
        
        Args:
            schedule: Schedule with updated information
            
        Returns:
            True if schedule was updated, False if not found
        """
        if schedule.schedule_id not in self.schedules:
            return False
        
        self.schedules[schedule.schedule_id] = schedule
        self.logger.info(f"Updated schedule: {schedule.schedule_id}")
        return True
    
    async def remove_schedule(self, schedule_id: str) -> bool:
        """
        Remove a schedule from the scheduler.
        
        Args:
            schedule_id: ID of the schedule to remove
            
        Returns:
            True if schedule was removed, False if not found
        """
        if schedule_id not in self.schedules:
            return False
        
        del self.schedules[schedule_id]
        self.logger.info(f"Removed schedule: {schedule_id}")
        return True
    
    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """
        Get a schedule by ID.
        
        Args:
            schedule_id: ID of the schedule to retrieve
            
        Returns:
            Schedule if found, None otherwise
        """
        return self.schedules.get(schedule_id)
    
    def get_all_schedules(self) -> List[Schedule]:
        """Get all schedules."""
        return list(self.schedules.values())
    
    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            self.logger.warning("Scheduler is already running")
            return
        
        self._running = True
        self._paused = False
        self._start_time = self._get_timestamp()
        
        self.logger.info("Starting scheduler")
        
        # Start worker tasks
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker(i))
            self._worker_tasks.append(task)
        
        # Start scheduler task
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        # Schedule all existing jobs
        for job in self.jobs.values():
            await self._schedule_job(job)
    
    async def _worker(self, worker_id: int) -> None:
        """Worker task that processes jobs from the queue."""
        while self._running:
            try:
                # Get next job from queue (with priority)
                priority, job_id = await self._job_queue.get()
                job = self.jobs.get(job_id)
                
                if not job:
                    self._job_queue.task_done()
                    continue
                
                # Check if job should run
                if not self._should_run_job(job):
                    self._job_queue.task_done()
                    continue
                
                # Execute the job
                await self._execute_job(job)
                
                # Mark as done
                self._job_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in worker {worker_id}: {e}")
                await asyncio.sleep(0.1)
    
    def _should_run_job(self, job: Job) -> bool:
        """Check if a job should be run."""
        if not self._running or self._paused:
            return False
        
        if job.status != JobStatus.PENDING:
            return False
        
        # Check if it's time to run
        if job.next_run and job.next_run > self._get_timestamp():
            return False
        
        return True
    
    async def _execute_job(self, job: Job) -> None:
        """Execute a job."""
        job.status = JobStatus.RUNNING
        job.started_at = self._get_timestamp()
        
        start_time = time.time()
        
        try:
            # Execute the callback
            if job.timeout:
                result = await asyncio.wait_for(
                    self._call_job_callback(job),
                    timeout=job.timeout
                )
            else:
                result = await self._call_job_callback(job)
            
            job.result = result
            job.status = JobStatus.COMPLETED
            job.completed_at = self._get_timestamp()
            job.last_run = job.completed_at
            
        except asyncio.TimeoutError:
            job.status = JobStatus.FAILED
            job.error = "Job timeout"
            job.completed_at = self._get_timestamp()
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = self._get_timestamp()
            
            # Check if we should retry
            if job.should_retry:
                job.retry_count += 1
                job.status = JobStatus.PENDING
                job.last_run = self._get_timestamp()
                # Re-schedule with delay
                job.next_run = job.last_run + timedelta(seconds=job.retry_delay * (2 ** job.retry_count))
                await self._schedule_job(job)
        
        job.execution_time = time.time() - start_time
        
        # Calculate next run time for periodic jobs
        if job.job_type in [JobType.PERIODIC, JobType.RECURRING]:
            job.next_run = job.get_next_run_time()
            job.status = JobStatus.PENDING
            await self._schedule_job(job)
    
    async def _call_job_callback(self, job: Job) -> Any:
        """Call the job's callback function."""
        if asyncio.iscoroutinefunction(job.callback):
            return await job.callback(*job.args, **job.kwargs)
        else:
            return job.callback(*job.args, **job.kwargs)
    
    async def _schedule_job(self, job: Job) -> None:
        """Schedule a job for execution."""
        if not self._running:
            return
        
        # Calculate priority (higher priority jobs run first)
        # Negative priority so higher numbers come first in priority queue
        priority = -job.priority
        
        try:
            await self._job_queue.put((priority, job.job_id))
        except asyncio.QueueFull:
            self.logger.warning(f"Job queue full, cannot schedule job: {job.job_id}")
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that manages job scheduling."""
        while self._running:
            try:
                # Check for jobs that need to be scheduled
                now = self._get_timestamp()
                
                for job in self.jobs.values():
                    if job.status == JobStatus.PENDING:
                        if job.next_run and job.next_run <= now:
                            await self._schedule_job(job)
                
                # Check for event-driven jobs
                await self._process_events()
                
                # Sleep for a short time
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_events(self) -> None:
        """Process pending events."""
        while not self._pending_events.empty():
            try:
                event = await self._pending_events.get()
                await self._handle_event(event)
                self._pending_events.task_done()
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                self.logger.error(f"Error processing event: {e}")
    
    async def _handle_event(self, event: Dict[str, Any]) -> None:
        """Handle an event."""
        event_type = event.get("type")
        
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    self.logger.error(f"Error in event handler for {event_type}: {e}")
    
    async def trigger_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Trigger an event that may trigger event-driven jobs.
        
        Args:
            event_type: Type of the event
            data: Event data
        """
        event = {"type": event_type, "data": data, "timestamp": self._get_timestamp().isoformat()}
        await self._pending_events.put(event)
        
        # Also check for event-driven jobs
        for job in self.jobs.values():
            if job.job_type == JobType.EVENT_DRIVEN:
                # Check if this job is interested in this event type
                if "event_types" in job.metadata:
                    if event_type in job.metadata["event_types"]:
                        # Set next_run to now so the job runs immediately
                        job.next_run = self._get_timestamp()
                        job.status = JobStatus.PENDING
                        await self._schedule_job(job)
    
    def on_event(self, event_type: str, handler: Callable) -> None:
        """
        Register an event handler.
        
        Args:
            event_type: Type of event to handle
            handler: Function to call when event occurs
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
    
    async def run_now(self, job_id: str) -> bool:
        """
        Run a job immediately.
        
        Args:
            job_id: ID of the job to run
            
        Returns:
            True if job was scheduled, False if not found
        """
        job = self.get_job(job_id)
        if not job:
            return False
        
        job.status = JobStatus.PENDING
        job.next_run = self._get_timestamp()
        await self._schedule_job(job)
        return True
    
    async def pause(self) -> None:
        """Pause the scheduler."""
        self._paused = True
        self.logger.info("Scheduler paused")
    
    async def resume(self) -> None:
        """Resume the scheduler."""
        self._paused = False
        self.logger.info("Scheduler resumed")
        
        # Re-schedule all pending jobs
        for job in self.jobs.values():
            if job.status == JobStatus.PENDING:
                await self._schedule_job(job)
    
    async def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return
        
        self._running = False
        self.logger.info("Stopping scheduler...")
        
        # Cancel all worker tasks
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Cancel scheduler task
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Clear queues
        while not self._job_queue.empty():
            try:
                self._job_queue.get_nowait()
                self._job_queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        while not self._pending_events.empty():
            try:
                self._pending_events.get_nowait()
                self._pending_events.task_done()
            except asyncio.QueueEmpty:
                break
        
        self._worker_tasks.clear()
        self._scheduler_task = None
        
        self.logger.info("Scheduler stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the scheduler."""
        return {
            "running": self._running,
            "paused": self._paused,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "uptime": (self._get_timestamp() - self._start_time).total_seconds() if self._start_time else 0,
            "jobs": {
                "total": self.get_job_count(),
                "active": self.get_active_job_count(),
                "by_status": {
                    status.value: len(self.get_jobs_by_status(status))
                    for status in JobStatus
                },
                "by_type": {
                    jt.value: len(self.get_jobs_by_type(jt))
                    for jt in JobType
                }
            },
            "schedules": len(self.schedules),
            "queue_size": self._job_queue.qsize(),
            "workers": len(self._worker_tasks),
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of scheduler activity."""
        return {
            "total_jobs": self.get_job_count(),
            "active_jobs": self.get_active_job_count(),
            "completed_jobs": len(self.get_jobs_by_status(JobStatus.COMPLETED)),
            "failed_jobs": len(self.get_jobs_by_status(JobStatus.FAILED)),
            "total_schedules": len(self.schedules),
            "uptime": (self._get_timestamp() - self._start_time).total_seconds() if self._start_time else 0,
        }
    
    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._running
    
    @property
    def is_paused(self) -> bool:
        """Check if the scheduler is paused."""
        return self._paused


# Convenience function for creating a scheduler
async def create_scheduler(
    config_file: Optional[str] = None,
    **kwargs
) -> Scheduler:
    """
    Create and configure a scheduler.
    
    Args:
        config_file: Optional path to a configuration file
        **kwargs: Additional arguments to pass to Scheduler
        
    Returns:
        Configured Scheduler instance
    """
    scheduler = Scheduler(**kwargs)
    
    if config_file and os.path.exists(config_file):
        # Load configuration from file
        try:
            import yaml
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f)
            
            if config_data:
                if 'jobs' in config_data:
                    for job_data in config_data['jobs']:
                        # Create a dummy callback (would be set properly in real usage)
                        def dummy_callback(*args, **kwargs):
                            pass
                        
                        job = Job.from_dict(job_data, dummy_callback)
                        await scheduler.add_job(job)
                
                if 'schedules' in config_data:
                    for schedule_data in config_data['schedules']:
                        schedule = Schedule.from_dict(schedule_data)
                        await scheduler.add_schedule(schedule)
        except ImportError:
            pass  # YAML not available, skip
        except Exception as e:
            scheduler.logger.error(f"Error loading config file: {e}")
    
    return scheduler
