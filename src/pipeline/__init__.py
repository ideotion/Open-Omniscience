"""
Pipeline Module for Open Omniscience

This module provides batch processing and task queue capabilities for the
Open Omniscience platform.

Modules:
- batch: Batch processing pipeline for historical data ingestion
- queue: SQLite-based task queue system

Author: Ideotion
"""

from .batch import BatchProcessor, BatchResult, BatchStatus, ProcessingConfig
from .queue import TaskQueue, QueueWorker, QueueManager, Task, TaskStatus, TaskPriority

__all__ = [
    # Batch processing
    'BatchProcessor',
    'BatchResult',
    'BatchStatus',
    'ProcessingConfig',
    # Task queue
    'TaskQueue',
    'QueueWorker',
    'QueueManager',
    'Task',
    'TaskStatus',
    'TaskPriority',
]

__version__ = "0.3.0"
