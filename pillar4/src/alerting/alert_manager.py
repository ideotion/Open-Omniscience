"""
Pillar 4: Real-Time Monitoring & Alerting System - Alert Manager

Manages alert creation, deduplication, lifecycle, and history.
"""

import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Callable, Tuple
from enum import Enum
import logging
from collections import defaultdict


class AlertStatus(Enum):
    NEW = "new"
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"
    DEDUPLICATED = "deduplicated"


class AlertSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertType(Enum):
    ANOMALY = "anomaly"
    TREND = "trend"
    THREAT = "threat"
    PATTERN = "pattern"
    SYSTEM = "system"
    CUSTOM = "custom"


@dataclass
class Alert:
    """Represents an alert."""
    id: str
    type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    status: AlertStatus = AlertStatus.NEW
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    resolved_at: Optional[float] = None
    closed_at: Optional[float] = None
    source: str = ""
    component: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "acknowledged_at": self.acknowledged_at,
            "resolved_at": self.resolved_at,
            "closed_at": self.closed_at,
            "source": self.source,
            "component": self.component,
            "tags": self.tags,
            "metadata": self.metadata,
            "fingerprint": self.fingerprint,
        }

    def __post_init__(self):
        if not self.fingerprint:
            self.fingerprint = self._generate_fingerprint()

    def _generate_fingerprint(self) -> str:
        """Generate a fingerprint for deduplication."""
        fingerprint_data = f"{self.type.value}:{self.severity.value}:{self.title}:{self.message}:{self.source}:{self.component}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]


@dataclass
class AlertRule:
    """Represents an alert rule."""
    id: str
    name: str
    description: str
    condition: Dict[str, Any]
    severity: AlertSeverity
    type: AlertType
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertStats:
    """Statistics for alerts."""
    total: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_type: Dict[str, int] = field(default_factory=dict)
    avg_resolution_time: float = 0.0
    last_alert_time: float = 0.0


class AlertManager:
    """
    Manages alerts with support for:
    - Alert creation, deduplication, and lifecycle management
    - Alert prioritization and severity levels
    - Alert correlation and grouping
    - Alert history and audit trail
    """

    def __init__(self):
        """Initialize the alert manager."""
        self.alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.rules: Dict[str, AlertRule] = {}
        self.fingerprint_index: Dict[str, str] = {}  # fingerprint -> alert_id
        self.tag_index: Dict[str, Set[str]] = defaultdict(set)  # tag -> set of alert_ids
        self.source_index: Dict[str, Set[str]] = defaultdict(set)  # source -> set of alert_ids
        self.stats = AlertStats()
        self.logger = logging.getLogger("AlertManager")

    def create_alert(
        self,
        type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        source: str = "",
        component: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        rule_id: Optional[str] = None,
    ) -> Optional[Alert]:
        """
        Create a new alert.

        Args:
            type: Type of the alert.
            severity: Severity level.
            title: Alert title.
            message: Alert message.
            source: Source of the alert.
            component: Component that generated the alert.
            tags: List of tags for the alert.
            metadata: Additional metadata.
            rule_id: ID of the rule that triggered the alert.

        Returns:
            The created alert, or None if deduplicated.
        """
        # Check for deduplication
        temp_alert = Alert(
            id="",
            type=type,
            severity=severity,
            title=title,
            message=message,
            source=source,
            component=component,
            tags=tags or [],
            metadata=metadata or {},
        )

        if self._is_duplicate(temp_alert):
            self.logger.info(f"Deduplicated alert: {title}")
            return None

        # Create the alert
        alert_id = self._generate_alert_id()
        alert = Alert(
            id=alert_id,
            type=type,
            severity=severity,
            title=title,
            message=message,
            source=source,
            component=component,
            tags=tags or [],
            metadata=metadata or {},
            created_at=time.time(),
            updated_at=time.time(),
        )

        # Add to storage
        self.alerts[alert_id] = alert
        self.fingerprint_index[alert.fingerprint] = alert_id

        # Update indexes
        for tag in alert.tags:
            self.tag_index[tag].add(alert_id)
        if alert.source:
            self.source_index[alert.source].add(alert_id)

        # Update stats
        self.stats.total += 1
        self.stats.by_status[alert.status.value] = self.stats.by_status.get(alert.status.value, 0) + 1
        self.stats.by_severity[alert.severity.value] = self.stats.by_severity.get(alert.severity.value, 0) + 1
        self.stats.by_type[alert.type.value] = self.stats.by_type.get(alert.type.value, 0) + 1
        self.stats.last_alert_time = time.time()

        self.logger.info(f"Created alert {alert_id}: {title} ({severity.value})")

        return alert

    def _is_duplicate(self, alert: Alert, window_seconds: float = 3600.0) -> bool:
        """
        Check if an alert is a duplicate.

        Args:
            alert: Alert to check.
            window_seconds: Time window for deduplication (default: 1 hour).

        Returns:
            True if the alert is a duplicate, False otherwise.
        """
        fingerprint = alert.fingerprint
        if fingerprint not in self.fingerprint_index:
            return False

        existing_id = self.fingerprint_index[fingerprint]
        existing_alert = self.alerts.get(existing_id)
        if not existing_alert:
            return False

        # Check if the existing alert is still open and within the time window
        if existing_alert.status in [AlertStatus.NEW, AlertStatus.OPEN]:
            if time.time() - existing_alert.created_at <= window_seconds:
                return True

        return False

    def _generate_alert_id(self) -> str:
        """Generate a unique alert ID."""
        return f"alert_{int(time.time() * 1000)}_{len(self.alerts)}"

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get an alert by ID."""
        return self.alerts.get(alert_id)

    def list_alerts(
        self,
        status: Optional[AlertStatus] = None,
        severity: Optional[AlertSeverity] = None,
        type: Optional[AlertType] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Alert]:
        """
        List alerts with optional filtering.

        Args:
            status: Filter by status.
            severity: Filter by severity.
            type: Filter by type.
            source: Filter by source.
            tag: Filter by tag.
            limit: Maximum number of alerts to return.
            offset: Offset for pagination.

        Returns:
            List of matching alerts.
        """
        alerts = list(self.alerts.values())

        # Apply filters
        if status:
            alerts = [a for a in alerts if a.status == status]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if type:
            alerts = [a for a in alerts if a.type == type]
        if source:
            alerts = [a for a in alerts if a.source == source]
        if tag:
            alert_ids = self.tag_index.get(tag, set())
            alerts = [a for a in alerts if a.id in alert_ids]

        # Sort by created_at (newest first) and apply pagination
        alerts.sort(key=lambda a: a.created_at, reverse=True)
        return alerts[offset:offset + limit]

    def acknowledge_alert(self, alert_id: str, user: Optional[str] = None) -> bool:
        """
        Acknowledge an alert.

        Args:
            alert_id: ID of the alert to acknowledge.
            user: User who acknowledged the alert.

        Returns:
            True if the alert was acknowledged, False otherwise.
        """
        alert = self.alerts.get(alert_id)
        if not alert:
            return False

        if alert.status != AlertStatus.NEW:
            return False

        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = time.time()
        alert.updated_at = time.time()

        if user:
            alert.metadata["acknowledged_by"] = user

        # Update stats
        self.stats.by_status[AlertStatus.NEW.value] -= 1
        self.stats.by_status[AlertStatus.ACKNOWLEDGED.value] = self.stats.by_status.get(AlertStatus.ACKNOWLEDGED.value, 0) + 1

        self.logger.info(f"Acknowledged alert {alert_id}")
        return True

    def resolve_alert(self, alert_id: str, user: Optional[str] = None, resolution: Optional[str] = None) -> bool:
        """
        Resolve an alert.

        Args:
            alert_id: ID of the alert to resolve.
            user: User who resolved the alert.
            resolution: Resolution notes.

        Returns:
            True if the alert was resolved, False otherwise.
        """
        alert = self.alerts.get(alert_id)
        if not alert:
            return False

        if alert.status not in [AlertStatus.NEW, AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]:
            return False

        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = time.time()
        alert.updated_at = time.time()

        if user:
            alert.metadata["resolved_by"] = user
        if resolution:
            alert.metadata["resolution"] = resolution

        # Update stats
        if alert.status == AlertStatus.NEW:
            self.stats.by_status[AlertStatus.NEW.value] -= 1
        elif alert.status == AlertStatus.OPEN:
            self.stats.by_status[AlertStatus.OPEN.value] -= 1
        elif alert.status == AlertStatus.ACKNOWLEDGED:
            self.stats.by_status[AlertStatus.ACKNOWLEDGED.value] -= 1

        self.stats.by_status[AlertStatus.RESOLVED.value] = self.stats.by_status.get(AlertStatus.RESOLVED.value, 0) + 1

        # Calculate resolution time
        if alert.created_at > 0 and alert.resolved_at:
            resolution_time = alert.resolved_at - alert.created_at
            if self.stats.avg_resolution_time == 0:
                self.stats.avg_resolution_time = resolution_time
            else:
                self.stats.avg_resolution_time = (
                    self.stats.avg_resolution_time * 0.9 +
                    resolution_time * 0.1
                )

        self.logger.info(f"Resolved alert {alert_id}")
        return True

    def close_alert(self, alert_id: str, user: Optional[str] = None) -> bool:
        """
        Close an alert.

        Args:
            alert_id: ID of the alert to close.
            user: User who closed the alert.

        Returns:
            True if the alert was closed, False otherwise.
        """
        alert = self.alerts.get(alert_id)
        if not alert:
            return False

        if alert.status == AlertStatus.CLOSED:
            return False

        alert.status = AlertStatus.CLOSED
        alert.closed_at = time.time()
        alert.updated_at = time.time()

        if user:
            alert.metadata["closed_by"] = user

        # Update stats
        if alert.status in self.stats.by_status:
            self.stats.by_status[alert.status.value] -= 1
        self.stats.by_status[AlertStatus.CLOSED.value] = self.stats.by_status.get(AlertStatus.CLOSED.value, 0) + 1

        # Move to history
        self.alert_history.append(alert)
        if len(self.alert_history) > 1000:  # Keep last 1000 alerts in history
            self.alert_history = self.alert_history[-1000:]

        # Remove from active alerts
        del self.alerts[alert_id]
        if alert.fingerprint in self.fingerprint_index:
            del self.fingerprint_index[alert.fingerprint]

        for tag in alert.tags:
            if tag in self.tag_index:
                self.tag_index[tag].discard(alert_id)
        if alert.source in self.source_index:
            self.source_index[alert.source].discard(alert_id)

        self.logger.info(f"Closed alert {alert_id}")
        return True

    def reopen_alert(self, alert_id: str, user: Optional[str] = None) -> bool:
        """
        Reopen a resolved or closed alert.

        Args:
            alert_id: ID of the alert to reopen.
            user: User who reopened the alert.

        Returns:
            True if the alert was reopened, False otherwise.
        """
        # Check if alert is in history (closed)
        alert = None
        for a in self.alert_history:
            if a.id == alert_id:
                alert = a
                break

        if not alert:
            alert = self.alerts.get(alert_id)
            if not alert:
                return False

        if alert.status not in [AlertStatus.RESOLVED, AlertStatus.CLOSED]:
            return False

        # Re-add to active alerts
        alert.status = AlertStatus.OPEN
        alert.updated_at = time.time()
        alert.resolved_at = None
        alert.closed_at = None

        if user:
            alert.metadata["reopened_by"] = user

        self.alerts[alert_id] = alert
        self.fingerprint_index[alert.fingerprint] = alert_id

        for tag in alert.tags:
            self.tag_index[tag].add(alert_id)
        if alert.source:
            self.source_index[alert.source].add(alert_id)

        # Update stats
        if AlertStatus.RESOLVED.value in self.stats.by_status:
            self.stats.by_status[AlertStatus.RESOLVED.value] -= 1
        if AlertStatus.CLOSED.value in self.stats.by_status:
            self.stats.by_status[AlertStatus.CLOSED.value] -= 1
        self.stats.by_status[AlertStatus.OPEN.value] = self.stats.by_status.get(AlertStatus.OPEN.value, 0) + 1

        self.logger.info(f"Reopened alert {alert_id}")
        return True

    def update_alert(
        self,
        alert_id: str,
        title: Optional[str] = None,
        message: Optional[str] = None,
        severity: Optional[AlertSeverity] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update an alert's properties.

        Args:
            alert_id: ID of the alert to update.
            title: New title.
            message: New message.
            severity: New severity.
            tags: New tags.
            metadata: New metadata.

        Returns:
            True if the alert was updated, False otherwise.
        """
        alert = self.alerts.get(alert_id)
        if not alert:
            return False

        if title:
            alert.title = title
        if message:
            alert.message = message
        if severity:
            # Update severity stats
            self.stats.by_severity[alert.severity.value] -= 1
            alert.severity = severity
            self.stats.by_severity[severity.value] = self.stats.by_severity.get(severity.value, 0) + 1

        if tags is not None:
            # Remove old tags from index
            for tag in alert.tags:
                if tag in self.tag_index:
                    self.tag_index[tag].discard(alert_id)
            # Add new tags to index
            alert.tags = tags
            for tag in tags:
                self.tag_index[tag].add(alert_id)

        if metadata:
            alert.metadata.update(metadata)

        alert.updated_at = time.time()
        # Regenerate fingerprint if title, message, or type changed
        if title or message:
            alert.fingerprint = alert._generate_fingerprint()
            self.fingerprint_index[alert.fingerprint] = alert_id

        self.logger.info(f"Updated alert {alert_id}")
        return True

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        self.rules[rule.id] = rule
        self.logger.info(f"Added alert rule: {rule.id}")

    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            self.logger.info(f"Removed alert rule: {rule_id}")
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """Get an alert rule by ID."""
        return self.rules.get(rule_id)

    def list_rules(self) -> List[AlertRule]:
        """List all alert rules."""
        return list(self.rules.values())

    def evaluate_rules(self, data: Dict[str, Any], source: str = "") -> List[Alert]:
        """
        Evaluate all rules against the given data.

        Args:
            data: Data to evaluate against rules.
            source: Source of the data.

        Returns:
            List of alerts triggered by the rules.
        """
        triggered_alerts = []

        for rule in self.rules.values():
            if not rule.enabled:
                continue

            try:
                if self._evaluate_condition(data, rule.condition):
                    alert = self.create_alert(
                        type=rule.type,
                        severity=rule.severity,
                        title=rule.name,
                        message=rule.description,
                        source=source,
                        component=rule.metadata.get("component", ""),
                        tags=rule.tags.copy(),
                        metadata={"rule_id": rule.id, "data": data},
                        rule_id=rule.id,
                    )
                    if alert:
                        triggered_alerts.append(alert)
            except Exception as e:
                self.logger.error(f"Error evaluating rule {rule.id}: {e}")

        return triggered_alerts

    def _evaluate_condition(self, data: Dict[str, Any], condition: Dict[str, Any]) -> bool:
        """
        Evaluate a rule condition against data.

        Args:
            data: Data to evaluate.
            condition: Condition to evaluate.

        Returns:
            True if the condition is satisfied, False otherwise.
        """
        # Simple condition evaluation - in production, use a more sophisticated system
        if "field" in condition and "operator" in condition and "value" in condition:
            field = condition["field"]
            operator = condition["operator"]
            value = condition["value"]

            if field not in data:
                return False

            data_value = data[field]

            if operator == "==":
                return data_value == value
            elif operator == "!=":
                return data_value != value
            elif operator == ">":
                return data_value > value
            elif operator == ">=":
                return data_value >= value
            elif operator == "<":
                return data_value < value
            elif operator == "<=":
                return data_value <= value
            elif operator == "in":
                return data_value in value
            elif operator == "not_in":
                return data_value not in value
            elif operator == "contains":
                if isinstance(data_value, str):
                    return value in data_value
                elif isinstance(data_value, (list, tuple)):
                    return value in data_value
                return False
            elif operator == "regex":
                if isinstance(data_value, str):
                    import re
                    return bool(re.search(value, data_value))
                return False

        elif "and" in condition:
            return all(self._evaluate_condition(data, sub_condition) for sub_condition in condition["and"])

        elif "or" in condition:
            return any(self._evaluate_condition(data, sub_condition) for sub_condition in condition["or"])

        elif "not" in condition:
            return not self._evaluate_condition(data, condition["not"])

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get alert manager statistics."""
        return {
            "total_alerts": self.stats.total,
            "active_alerts": len(self.alerts),
            "by_status": self.stats.by_status,
            "by_severity": self.stats.by_severity,
            "by_type": self.stats.by_type,
            "avg_resolution_time": self.stats.avg_resolution_time,
            "last_alert_time": self.stats.last_alert_time,
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules.values() if r.enabled),
        }

    def cleanup(self, max_age_seconds: float = 86400.0) -> int:
        """
        Clean up old alerts.

        Args:
            max_age_seconds: Maximum age of alerts to keep (default: 24 hours).

        Returns:
            Number of alerts cleaned up.
        """
        cutoff = time.time() - max_age_seconds
        cleaned = 0

        # Clean up closed alerts from history
        self.alert_history = [a for a in self.alert_history if a.closed_at and a.closed_at > cutoff]
        cleaned += len(self.alert_history)

        return cleaned
