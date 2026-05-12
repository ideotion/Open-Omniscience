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
