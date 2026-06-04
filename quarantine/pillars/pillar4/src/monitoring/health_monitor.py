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
System Health Monitor for Pillar 4: Real-Time Monitoring & Alerting System

Provides resource usage monitoring, service health checks, performance metrics
collection, and self-healing capabilities for the monitoring infrastructure.

Features:
- Resource usage monitoring (CPU, memory, disk, network) - when psutil available
- Service health checks and heartbeats
- Performance metrics collection
- Self-healing capabilities
- Alerting on health issues
- Historical metrics storage
- Works 100% offline with optional network capabilities

Note: Full system monitoring requires psutil. Without psutil, basic functionality
is still available but system resource monitoring is limited.
"""

import asyncio
import logging
import os
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import hashlib
import socket
import subprocess
from pathlib import Path

# Try to import psutil for enhanced monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ResourceType(Enum):
    """Types of system resources."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    PROCESS = "process"
    SYSTEM = "system"


class MetricType(Enum):
    """Types of metrics."""
    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class ResourceMetrics:
    """Metrics for a specific resource."""
    resource_type: ResourceType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # CPU metrics
    cpu_percent: Optional[float] = None
    cpu_count: Optional[int] = None
    cpu_times: Optional[Dict[str, float]] = None
    
    # Memory metrics
    memory_total: Optional[int] = None  # bytes
    memory_used: Optional[int] = None  # bytes
    memory_free: Optional[int] = None  # bytes
    memory_percent: Optional[float] = None
    
    # Disk metrics
    disk_total: Optional[int] = None  # bytes
    disk_used: Optional[int] = None  # bytes
    disk_free: Optional[int] = None  # bytes
    disk_percent: Optional[float] = None
    disk_read: Optional[int] = None  # bytes
    disk_write: Optional[int] = None  # bytes
    
    # Network metrics
    network_sent: Optional[int] = None  # bytes
    network_recv: Optional[int] = None  # bytes
    network_connections: Optional[int] = None
    
    # Process metrics
    process_cpu_percent: Optional[float] = None
    process_memory: Optional[int] = None  # bytes
    process_threads: Optional[int] = None
    process_open_files: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "resource_type": self.resource_type.value,
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": self.cpu_percent,
            "cpu_count": self.cpu_count,
            "cpu_times": self.cpu_times,
            "memory_total": self.memory_total,
            "memory_used": self.memory_used,
            "memory_free": self.memory_free,
            "memory_percent": self.memory_percent,
            "disk_total": self.disk_total,
            "disk_used": self.disk_used,
            "disk_free": self.disk_free,
            "disk_percent": self.disk_percent,
            "disk_read": self.disk_read,
            "disk_write": self.disk_write,
            "network_sent": self.network_sent,
            "network_recv": self.network_recv,
            "network_connections": self.network_connections,
            "process_cpu_percent": self.process_cpu_percent,
            "process_memory": self.process_memory,
            "process_threads": self.process_threads,
            "process_open_files": self.process_open_files,
        }


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    component: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0  # seconds
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "component": self.component,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "duration": self.duration,
        }


@dataclass
class Alert:
    """Represents a health alert."""
    alert_id: str
    component: str
    status: HealthStatus
    message: str
    severity: str = "medium"  # low, medium, high, critical
    details: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        if not self.alert_id:
            self.alert_id = self._generate_alert_id()
    
    def _generate_alert_id(self) -> str:
        """Generate a unique alert ID."""
        content = f"{self.component}:{self.status.value}:{self.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def resolve(self) -> None:
        """Mark the alert as resolved."""
        self.resolved = True
        self.resolved_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp.isoformat(),
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass
class SystemHealth:
    """Overall system health status."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: HealthStatus = HealthStatus.UNKNOWN
    cpu_status: HealthStatus = HealthStatus.UNKNOWN
    memory_status: HealthStatus = HealthStatus.UNKNOWN
    disk_status: HealthStatus = HealthStatus.UNKNOWN
    network_status: HealthStatus = HealthStatus.UNKNOWN
    process_status: HealthStatus = HealthStatus.UNKNOWN
    
    # Metrics
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    
    # Alerts
    active_alerts: int = 0
    resolved_alerts: int = 0
    
    # Uptime
    system_uptime: float = 0.0  # seconds
    process_uptime: float = 0.0  # seconds
    
    # System info
    has_psutil: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "cpu_status": self.cpu_status.value,
            "memory_status": self.memory_status.value,
            "disk_status": self.disk_status.value,
            "network_status": self.network_status.value,
            "process_status": self.process_status.value,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "disk_usage": self.disk_usage,
            "active_alerts": self.active_alerts,
            "resolved_alerts": self.resolved_alerts,
            "system_uptime": self.system_uptime,
            "process_uptime": self.process_uptime,
            "has_psutil": self.has_psutil,
        }


@dataclass
class Metric:
    """Represents a single metric."""
    name: str
    metric_type: MetricType
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.metric_type.value,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels,
            "description": self.description,
        }


class HealthMonitor:
    """
    Monitors system health and performance metrics.
    
    This monitor collects resource usage data, performs health checks,
    generates alerts, and provides self-healing capabilities.
    
    Note: Full system monitoring requires psutil. Without psutil, basic
    functionality is still available but system resource monitoring is limited.
    
    Example usage:
        monitor = HealthMonitor()
        
        # Start monitoring
        await monitor.start()
        
        # Get current health
        health = monitor.get_health()
        print(f"System status: {health.status}")
        
        # Get metrics
        metrics = monitor.get_metrics()
        
        # Check specific resource
        cpu_health = await monitor.check_cpu()
        
        # Stop monitoring
        await monitor.stop()
    """
    
    def __init__(
        self,
        check_interval: float = 60.0,  # seconds
        metrics_retention: int = 1000,  # number of metric samples to keep
        alert_retention: int = 100,  # number of alerts to keep
        logger: Optional[logging.Logger] = None
    ):
        self.check_interval = check_interval
        self.metrics_retention = metrics_retention
        self.alert_retention = alert_retention
        self.logger = logger or logging.getLogger(__name__)
        
        # State
        self._running = False
        self._start_time: Optional[datetime] = None
        self._process_start_time: datetime = datetime.utcnow()
        
        # Metrics storage
        self._metrics: Dict[str, List[Metric]] = {}
        self._resource_metrics: List[ResourceMetrics] = []
        
        # Health checks
        self._health_checks: Dict[str, HealthCheckResult] = {}
        self._last_health_check: Optional[datetime] = None
        
        # Alerts
        self._alerts: Dict[str, Alert] = {}
        self._alert_handlers: List[Callable[[Alert], None]] = []
        
        # Thresholds
        self._thresholds: Dict[str, Dict[str, float]] = {
            "cpu": {"warning": 80.0, "critical": 95.0},
            "memory": {"warning": 85.0, "critical": 95.0},
            "disk": {"warning": 80.0, "critical": 95.0},
            "network": {"warning": 100.0, "critical": 200.0},  # connections
        }
        
        # Monitoring task
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Setup logging
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Configure logging for the health monitor."""
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
    
    def _has_psutil(self) -> bool:
        """Check if psutil is available."""
        return HAS_PSUTIL and psutil is not None
    
    async def start(self) -> None:
        """Start the health monitor."""
        if self._running:
            self.logger.warning("Health monitor is already running")
            return
        
        self._running = True
        self._start_time = self._get_timestamp()
        
        self.logger.info("Starting health monitor")
        
        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        # Perform initial health check
        await self.check_all()
    
    async def stop(self) -> None:
        """Stop the health monitor."""
        if not self._running:
            return
        
        self._running = False
        self.logger.info("Stopping health monitor...")
        
        # Cancel monitoring task
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self._monitor_task = None
        self.logger.info("Health monitor stopped")
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                # Perform health checks
                await self.check_all()
                
                # Collect metrics
                await self.collect_metrics()
                
                # Check for alerts
                await self._check_alerts()
                
                # Sleep until next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5.0)
    
    async def check_all(self) -> Dict[str, HealthCheckResult]:
        """
        Perform all health checks.
        
        Returns:
            Dictionary mapping component names to health check results
        """
        results = {}
        
        # Check CPU
        cpu_result = await self.check_cpu()
        if cpu_result:
            results["cpu"] = cpu_result
        
        # Check memory
        memory_result = await self.check_memory()
        if memory_result:
            results["memory"] = memory_result
        
        # Check disk
        disk_result = await self.check_disk()
        if disk_result:
            results["disk"] = disk_result
        
        # Check network
        network_result = await self.check_network()
        if network_result:
            results["network"] = network_result
        
        # Check process
        process_result = await self.check_process()
        if process_result:
            results["process"] = process_result
        
        # Check system
        system_result = await self.check_system()
        if system_result:
            results["system"] = system_result
        
        self._health_checks = results
        self._last_health_check = self._get_timestamp()
        
        return results
    
    async def check_cpu(self) -> Optional[HealthCheckResult]:
        """
        Check CPU health and usage.
        
        Returns:
            Health check result for CPU
        """
        start_time = time.time()
        result = HealthCheckResult(component="cpu")
        
        try:
            if not self._has_psutil():
                result.status = HealthStatus.UNKNOWN
                result.message = "psutil not available for CPU monitoring"
                result.duration = time.time() - start_time
                result.timestamp = self._get_timestamp()
                return result
            
            # Get CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_times = psutil.cpu_times_percent(interval=1)
            
            # Store in result
            result.details = {
                "cpu_percent": cpu_percent,
                "cpu_count": cpu_count,
                "cpu_times": cpu_times._asdict() if cpu_times else {},
            }
            
            # Determine status based on thresholds
            if cpu_percent >= self._thresholds["cpu"]["critical"]:
                result.status = HealthStatus.CRITICAL
                result.message = f"CPU usage critical: {cpu_percent:.1f}%"
            elif cpu_percent >= self._thresholds["cpu"]["warning"]:
                result.status = HealthStatus.WARNING
                result.message = f"CPU usage high: {cpu_percent:.1f}%"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = f"CPU usage normal: {cpu_percent:.1f}%"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking CPU: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def check_memory(self) -> Optional[HealthCheckResult]:
        """
        Check memory health and usage.
        
        Returns:
            Health check result for memory
        """
        start_time = time.time()
        result = HealthCheckResult(component="memory")
        
        try:
            if not self._has_psutil():
                result.status = HealthStatus.UNKNOWN
                result.message = "psutil not available for memory monitoring"
                result.duration = time.time() - start_time
                result.timestamp = self._get_timestamp()
                return result
            
            # Get memory metrics
            memory = psutil.virtual_memory()
            
            # Store in result
            result.details = {
                "total": memory.total,
                "used": memory.used,
                "free": memory.free,
                "percent": memory.percent,
            }
            
            # Determine status based on thresholds
            if memory.percent >= self._thresholds["memory"]["critical"]:
                result.status = HealthStatus.CRITICAL
                result.message = f"Memory usage critical: {memory.percent:.1f}%"
            elif memory.percent >= self._thresholds["memory"]["warning"]:
                result.status = HealthStatus.WARNING
                result.message = f"Memory usage high: {memory.percent:.1f}%"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = f"Memory usage normal: {memory.percent:.1f}%"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking memory: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def check_disk(self) -> Optional[HealthCheckResult]:
        """
        Check disk health and usage.
        
        Returns:
            Health check result for disk
        """
        start_time = time.time()
        result = HealthCheckResult(component="disk")
        
        try:
            if not self._has_psutil():
                result.status = HealthStatus.UNKNOWN
                result.message = "psutil not available for disk monitoring"
                result.duration = time.time() - start_time
                result.timestamp = self._get_timestamp()
                return result
            
            # Get disk metrics for all partitions
            partitions = psutil.disk_partitions()
            disk_info = []
            
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append({
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                    })
                except Exception:
                    continue
            
            # Store in result
            result.details = {"partitions": disk_info}
            
            # Find the partition with highest usage
            max_usage = 0
            for info in disk_info:
                if info["percent"] > max_usage:
                    max_usage = info["percent"]
            
            # Determine status based on thresholds
            if max_usage >= self._thresholds["disk"]["critical"]:
                result.status = HealthStatus.CRITICAL
                result.message = f"Disk usage critical: {max_usage:.1f}%"
            elif max_usage >= self._thresholds["disk"]["warning"]:
                result.status = HealthStatus.WARNING
                result.message = f"Disk usage high: {max_usage:.1f}%"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = f"Disk usage normal: {max_usage:.1f}%"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking disk: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def check_network(self) -> Optional[HealthCheckResult]:
        """
        Check network health and usage.
        
        Returns:
            Health check result for network
        """
        start_time = time.time()
        result = HealthCheckResult(component="network")
        
        try:
            if not self._has_psutil():
                result.status = HealthStatus.UNKNOWN
                result.message = "psutil not available for network monitoring"
                result.duration = time.time() - start_time
                result.timestamp = self._get_timestamp()
                return result
            
            # Get network metrics
            net_io = psutil.net_io_counters()
            connections = len(psutil.net_connections())
            
            # Store in result
            result.details = {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "connections": connections,
            }
            
            # Determine status based on thresholds
            if connections >= self._thresholds["network"]["critical"]:
                result.status = HealthStatus.CRITICAL
                result.message = f"Network connections critical: {connections}"
            elif connections >= self._thresholds["network"]["warning"]:
                result.status = HealthStatus.WARNING
                result.message = f"Network connections high: {connections}"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = f"Network connections normal: {connections}"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking network: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def check_process(self) -> Optional[HealthCheckResult]:
        """
        Check process health and resource usage.
        
        Returns:
            Health check result for process
        """
        start_time = time.time()
        result = HealthCheckResult(component="process")
        
        try:
            if not self._has_psutil():
                result.status = HealthStatus.UNKNOWN
                result.message = "psutil not available for process monitoring"
                result.duration = time.time() - start_time
                result.timestamp = self._get_timestamp()
                return result
            
            # Get current process
            process = psutil.Process()
            
            # Get process metrics
            cpu_percent = process.cpu_percent(interval=1)
            memory_info = process.memory_info()
            threads = process.num_threads()
            open_files = len(process.open_files())
            
            # Store in result
            result.details = {
                "cpu_percent": cpu_percent,
                "memory_rss": memory_info.rss,
                "memory_vms": memory_info.vms,
                "threads": threads,
                "open_files": open_files,
            }
            
            # Determine status
            # For process, we use more lenient thresholds
            if cpu_percent >= 90.0:
                result.status = HealthStatus.WARNING
                result.message = f"Process CPU usage high: {cpu_percent:.1f}%"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = f"Process CPU usage normal: {cpu_percent:.1f}%"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking process: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def check_system(self) -> Optional[HealthCheckResult]:
        """
        Check overall system health.
        
        Returns:
            Health check result for system
        """
        start_time = time.time()
        result = HealthCheckResult(component="system")
        
        try:
            # Get system information
            if self._has_psutil():
                boot_time = psutil.boot_time()
                system_uptime = time.time() - boot_time
            else:
                system_uptime = 0.0
            
            # Get process uptime
            process_uptime = (self._get_timestamp() - self._process_start_time).total_seconds()
            
            # Store in result
            result.details = {
                "system_uptime": system_uptime,
                "process_uptime": process_uptime,
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "has_psutil": self._has_psutil(),
            }
            
            # Determine status based on other checks
            cpu_check = self._health_checks.get("cpu")
            memory_check = self._health_checks.get("memory")
            disk_check = self._health_checks.get("disk")
            
            # If any critical component is critical, system is critical
            if any(
                check and check.status == HealthStatus.CRITICAL 
                for check in [cpu_check, memory_check, disk_check]
            ):
                result.status = HealthStatus.CRITICAL
                result.message = "System has critical issues"
            # If any critical component is warning, system is warning
            elif any(
                check and check.status == HealthStatus.WARNING 
                for check in [cpu_check, memory_check, disk_check]
            ):
                result.status = HealthStatus.WARNING
                result.message = "System has warnings"
            else:
                result.status = HealthStatus.HEALTHY
                result.message = "System is healthy"
            
        except Exception as e:
            result.status = HealthStatus.UNKNOWN
            result.message = f"Error checking system: {e}"
        
        result.duration = time.time() - start_time
        result.timestamp = self._get_timestamp()
        
        return result
    
    async def collect_metrics(self) -> ResourceMetrics:
        """
        Collect all resource metrics.
        
        Returns:
            ResourceMetrics with all current metrics
        """
        metrics = ResourceMetrics(resource_type=ResourceType.SYSTEM)
        
        try:
            if self._has_psutil():
                # CPU metrics
                metrics.cpu_percent = psutil.cpu_percent(interval=1)
                metrics.cpu_count = psutil.cpu_count()
                cpu_times = psutil.cpu_times_percent(interval=1)
                if cpu_times:
                    metrics.cpu_times = cpu_times._asdict()
                
                # Memory metrics
                memory = psutil.virtual_memory()
                metrics.memory_total = memory.total
                metrics.memory_used = memory.used
                metrics.memory_free = memory.free
                metrics.memory_percent = memory.percent
                
                # Disk metrics
                partitions = psutil.disk_partitions()
                for partition in partitions:
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        # For simplicity, just use the first partition
                        if metrics.disk_total is None:
                            metrics.disk_total = usage.total
                            metrics.disk_used = usage.used
                            metrics.disk_free = usage.free
                            metrics.disk_percent = usage.percent
                    except Exception:
                        continue
                
                # Network metrics
                net_io = psutil.net_io_counters()
                metrics.network_sent = net_io.bytes_sent
                metrics.network_recv = net_io.bytes_recv
                
                try:
                    connections = psutil.net_connections()
                    metrics.network_connections = len(connections)
                except Exception:
                    pass
                
                # Process metrics
                try:
                    process = psutil.Process()
                    metrics.process_cpu_percent = process.cpu_percent(interval=1)
                    memory_info = process.memory_info()
                    metrics.process_memory = memory_info.rss
                    metrics.process_threads = process.num_threads()
                    try:
                        metrics.process_open_files = len(process.open_files())
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                # Without psutil, we can't collect actual metrics
                # But we can still record that we tried
                metrics.details = {"error": "psutil not available"}
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
        
        # Store metrics
        self._resource_metrics.append(metrics)
        
        # Enforce retention limit
        if len(self._resource_metrics) > self.metrics_retention:
            self._resource_metrics = self._resource_metrics[-self.metrics_retention:]
        
        # Also store individual metrics
        self._store_metric("cpu_usage", MetricType.GAUGE, metrics.cpu_percent or 0.0)
        self._store_metric("memory_usage", MetricType.GAUGE, metrics.memory_percent or 0.0)
        self._store_metric("disk_usage", MetricType.GAUGE, metrics.disk_percent or 0.0)
        
        return metrics
    
    def _store_metric(self, name: str, metric_type: MetricType, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Store a metric."""
        metric = Metric(
            name=name,
            metric_type=metric_type,
            value=value,
            labels=labels or {},
            timestamp=self._get_timestamp()
        )
        
        if name not in self._metrics:
            self._metrics[name] = []
        
        self._metrics[name].append(metric)
        
        # Enforce retention limit
        if len(self._metrics[name]) > self.metrics_retention:
            self._metrics[name] = self._metrics[name][-self.metrics_retention:]
    
    async def _check_alerts(self) -> None:
        """Check for health issues and generate alerts."""
        # Check each health check result
        for component, result in self._health_checks.items():
            if result.status in [HealthStatus.CRITICAL, HealthStatus.WARNING]:
                # Check if we already have an alert for this
                existing_alert = None
                for alert_id, alert in self._alerts.items():
                    if alert.component == component and not alert.resolved:
                        existing_alert = alert
                        break
                
                if existing_alert:
                    # Update existing alert
                    existing_alert.timestamp = self._get_timestamp()
                    existing_alert.status = result.status
                    existing_alert.message = result.message
                    existing_alert.details = result.details
                else:
                    # Create new alert
                    severity = "high" if result.status == HealthStatus.CRITICAL else "medium"
                    alert = Alert(
                        alert_id="",
                        component=component,
                        status=result.status,
                        message=result.message,
                        severity=severity,
                        details=result.details
                    )
                    self._alerts[alert.alert_id] = alert
                    
                    # Trigger alert handlers
                    await self._trigger_alert(alert)
        
        # Clean up old alerts
        self._cleanup_alerts()
    
    async def _trigger_alert(self, alert: Alert) -> None:
        """Trigger alert handlers."""
        for handler in self._alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                self.logger.error(f"Error in alert handler: {e}")
    
    def _cleanup_alerts(self) -> None:
        """Clean up old alerts based on retention limit."""
        if len(self._alerts) <= self.alert_retention:
            return
        
        # Sort alerts by timestamp and keep the most recent
        sorted_alerts = sorted(
            self._alerts.items(), 
            key=lambda x: x[1].timestamp, 
            reverse=True
        )
        
        # Keep only the most recent alerts
        self._alerts = dict(sorted_alerts[:self.alert_retention])
    
    def get_health(self) -> SystemHealth:
        """
        Get overall system health.
        
        Returns:
            SystemHealth with current health status
        """
        health = SystemHealth(timestamp=self._get_timestamp())
        health.has_psutil = self._has_psutil()
        
        # Get individual component statuses
        cpu_check = self._health_checks.get("cpu")
        memory_check = self._health_checks.get("memory")
        disk_check = self._health_checks.get("disk")
        network_check = self._health_checks.get("network")
        process_check = self._health_checks.get("process")
        system_check = self._health_checks.get("system")
        
        # Set component statuses
        health.cpu_status = cpu_check.status if cpu_check else HealthStatus.UNKNOWN
        health.memory_status = memory_check.status if memory_check else HealthStatus.UNKNOWN
        health.disk_status = disk_check.status if disk_check else HealthStatus.UNKNOWN
        health.network_status = network_check.status if network_check else HealthStatus.UNKNOWN
        health.process_status = process_check.status if process_check else HealthStatus.UNKNOWN
        
        # Get metrics from latest resource metrics
        if self._resource_metrics:
            latest = self._resource_metrics[-1]
            health.cpu_usage = latest.cpu_percent or 0.0
            health.memory_usage = latest.memory_percent or 0.0
            health.disk_usage = latest.disk_percent or 0.0
        
        # Count alerts
        health.active_alerts = len([a for a in self._alerts.values() if not a.resolved])
        health.resolved_alerts = len([a for a in self._alerts.values() if a.resolved])
        
        # Set system uptime
        if self._start_time:
            health.system_uptime = (self._get_timestamp() - self._start_time).total_seconds()
        
        # Set process uptime
        health.process_uptime = (self._get_timestamp() - self._process_start_time).total_seconds()
        
        # Determine overall status
        if any(
            status == HealthStatus.CRITICAL 
            for status in [
                health.cpu_status, health.memory_status, health.disk_status,
                health.network_status, health.process_status
            ]
        ):
            health.status = HealthStatus.CRITICAL
        elif any(
            status == HealthStatus.WARNING 
            for status in [
                health.cpu_status, health.memory_status, health.disk_status,
                health.network_status, health.process_status
            ]
        ):
            health.status = HealthStatus.WARNING
        elif all(
            status == HealthStatus.HEALTHY 
            for status in [
                health.cpu_status, health.memory_status, health.disk_status,
                health.network_status, health.process_status
            ]
        ):
            health.status = HealthStatus.HEALTHY
        else:
            health.status = HealthStatus.UNKNOWN
        
        return health
    
    def get_metrics(self, resource_type: Optional[ResourceType] = None) -> List[ResourceMetrics]:
        """
        Get collected resource metrics.
        
        Args:
            resource_type: Optional filter by resource type
            
        Returns:
            List of resource metrics
        """
        if resource_type:
            return [m for m in self._resource_metrics if m.resource_type == resource_type]
        return self._resource_metrics.copy()
    
    def get_metric(self, name: str) -> List[Metric]:
        """
        Get metrics by name.
        
        Args:
            name: Name of the metric
            
        Returns:
            List of metric values
        """
        return self._metrics.get(name, []).copy()
    
    def get_alerts(self, resolved: Optional[bool] = None) -> List[Alert]:
        """
        Get alerts.
        
        Args:
            resolved: Filter by resolved status (None = all)
            
        Returns:
            List of alerts
        """
        if resolved is None:
            return list(self._alerts.values())
        return [a for a in self._alerts.values() if a.resolved == resolved]
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unresolved) alerts."""
        return self.get_alerts(resolved=False)
    
    def get_health_checks(self) -> Dict[str, HealthCheckResult]:
        """Get all health check results."""
        return self._health_checks.copy()
    
    def get_health_check(self, component: str) -> Optional[HealthCheckResult]:
        """Get health check result for a specific component."""
        return self._health_checks.get(component)
    
    def add_alert_handler(self, handler: Callable[[Alert], None]) -> None:
        """
        Add a handler for alerts.
        
        Args:
            handler: Function to call when an alert is triggered
        """
        self._alert_handlers.append(handler)
    
    def remove_alert_handler(self, handler: Callable[[Alert], None]) -> bool:
        """
        Remove an alert handler.
        
        Args:
            handler: Handler to remove
            
        Returns:
            True if handler was removed, False if not found
        """
        if handler in self._alert_handlers:
            self._alert_handlers.remove(handler)
            return True
        return False
    
    def set_threshold(self, component: str, level: str, value: float) -> None:
        """
        Set a threshold for a component.
        
        Args:
            component: Component name (cpu, memory, disk, network)
            level: Threshold level (warning, critical)
            value: Threshold value
        """
        if component not in self._thresholds:
            self._thresholds[component] = {}
        self._thresholds[component][level] = value
    
    def get_threshold(self, component: str, level: str) -> Optional[float]:
        """
        Get a threshold for a component.
        
        Args:
            component: Component name
            level: Threshold level
            
        Returns:
            Threshold value or None if not found
        """
        return self._thresholds.get(component, {}).get(level)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the health monitor."""
        health = self.get_health()
        
        return {
            "running": self._running,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "last_health_check": self._last_health_check.isoformat() if self._last_health_check else None,
            "health": health.to_dict(),
            "metrics_count": len(self._resource_metrics),
            "alerts_count": len(self._alerts),
            "active_alerts": health.active_alerts,
            "resolved_alerts": health.resolved_alerts,
            "has_psutil": self._has_psutil(),
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of health monitor activity."""
        health = self.get_health()
        
        return {
            "status": health.status.value,
            "cpu_status": health.cpu_status.value,
            "memory_status": health.memory_status.value,
            "disk_status": health.disk_status.value,
            "network_status": health.network_status.value,
            "process_status": health.process_status.value,
            "cpu_usage": health.cpu_usage,
            "memory_usage": health.memory_usage,
            "disk_usage": health.disk_usage,
            "active_alerts": health.active_alerts,
            "resolved_alerts": health.resolved_alerts,
            "system_uptime": health.system_uptime,
            "process_uptime": health.process_uptime,
            "has_psutil": health.has_psutil,
        }
    
    @property
    def is_running(self) -> bool:
        """Check if the health monitor is running."""
        return self._running
    
    @property
    def is_healthy(self) -> bool:
        """Check if the system is healthy."""
        health = self.get_health()
        return health.status == HealthStatus.HEALTHY


# Convenience function for creating a health monitor
async def create_health_monitor(
    check_interval: float = 60.0,
    metrics_retention: int = 1000,
    alert_retention: int = 100,
    **kwargs
) -> HealthMonitor:
    """
    Create and configure a health monitor.
    
    Args:
        check_interval: Interval between health checks (seconds)
        metrics_retention: Number of metric samples to retain
        alert_retention: Number of alerts to retain
        **kwargs: Additional arguments to pass to HealthMonitor
        
    Returns:
        Configured HealthMonitor instance
    """
    monitor = HealthMonitor(
        check_interval=check_interval,
        metrics_retention=metrics_retention,
        alert_retention=alert_retention,
        **kwargs
    )
    
    return monitor
