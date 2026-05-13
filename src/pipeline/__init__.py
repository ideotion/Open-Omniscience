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
