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
Monitoring Module for Pillar 4: Real-Time Monitoring & Alerting System

This module contains the core monitoring infrastructure:
- Stream processing engine
- Source management and health monitoring
- Monitoring schedule management
- System health monitoring
"""

from .stream_processor import (
    StreamProcessor,
    BatchStreamProcessor,
    StreamConfig,
    StreamStatus,
    StreamType,
    StreamStats,
    ProcessedItem,
    create_stream_processor,
)

from .source_manager import (
    SourceManager,
    Source,
    SourceCategory,
    SourcePriority,
    SourceHealthStatus,
    SourceStatus,
    SourceHealthCheck,
    create_source_manager,
)

from .scheduler import (
    Scheduler,
    Job,
    Schedule,
    JobStatus,
    JobType,
    ScheduleType,
    create_scheduler,
)

from .health_monitor import (
    HealthMonitor,
    HealthStatus,
    ResourceType,
    MetricType,
    ResourceMetrics,
    HealthCheckResult,
    Alert,
    SystemHealth,
    Metric,
    create_health_monitor,
)

__all__ = [
    # Stream Processor
    "StreamProcessor",
    "BatchStreamProcessor",
    "StreamConfig",
    "StreamStatus",
    "StreamType",
    "StreamStats",
    "ProcessedItem",
    "create_stream_processor",
    
    # Source Manager
    "SourceManager",
    "Source",
    "SourceCategory",
    "SourcePriority",
    "SourceHealthStatus",
    "SourceStatus",
    "SourceHealthCheck",
    "create_source_manager",
    
    # Scheduler
    "Scheduler",
    "Job",
    "Schedule",
    "JobStatus",
    "JobType",
    "ScheduleType",
    "create_scheduler",
    
    # Health Monitor
    "HealthMonitor",
    "HealthStatus",
    "ResourceType",
    "MetricType",
    "ResourceMetrics",
    "HealthCheckResult",
    "Alert",
    "SystemHealth",
    "Metric",
    "create_health_monitor",
]
