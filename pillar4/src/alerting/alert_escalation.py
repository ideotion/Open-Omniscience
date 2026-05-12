"""
Pillar 4: Real-Time Monitoring & Alerting System - Alert Escalation

Handles alert escalation policies and multi-level escalation paths.
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Callable, Tuple
from enum import Enum
import logging
from collections import defaultdict


class EscalationLevel(Enum):
    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"
    LEVEL_4 = "level_4"
    LEVEL_5 = "level_5"


class EscalationStatus(Enum):
    PENDING = "pending"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class EscalationTrigger(Enum):
    TIME_BASED = "time_based"  # After a certain time period
    SEVERITY_BASED = "severity_based"  # Based on alert severity
    COUNT_BASED = "count_based"  # After a certain number of occurrences
    MANUAL = "manual"  # Manually triggered


@dataclass
class EscalationAction:
    """An action to take during escalation."""
    action_type: str  # notify, run_script, create_ticket, etc.
    target: str  # e.g., notification channel, script path, ticket system
    parameters: Dict[str, Any] = field(default_factory=dict)
    delay: float = 0.0  # Delay before executing this action


@dataclass
class EscalationPath:
    """A path for escalating alerts."""
    id: str
    name: str
    description: str
    levels: List[EscalationLevel] = field(default_factory=list)
    triggers: List[EscalationTrigger] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class EscalationPolicy:
    """A complete escalation policy."""
    id: str
    name: str
    description: str
    default_path: str
    paths: Dict[str, EscalationPath] = field(default_factory=dict)
    severity_mapping: Dict[str, str] = field(default_factory=dict)  # severity -> path_id
    tag_mapping: Dict[str, str] = field(default_factory=dict)  # tag -> path_id
    enabled: bool = True


@dataclass
class EscalationState:
    """Tracks the escalation state of an alert."""
    alert_id: str
    policy_id: str
    path_id: str
    current_level: EscalationLevel
    status: EscalationStatus
    created_at: float
    updated_at: float
    escalation_times: Dict[str, float] = field(default_factory=dict)  # level -> timestamp
    actions_taken: List[Tuple[str, float, bool]] = field(default_factory=list)  # (action_id, timestamp, success)


class AlertEscalationPolicy:
    """
    Manages alert escalation with support for:
    - Multi-level escalation paths
    - Automatic escalation for unacknowledged alerts
    - Escalation history tracking
    - Time-based, severity-based, and count-based triggers
    """

    def __init__(self):
        """Initialize the alert escalation policy manager."""
        self.policies: Dict[str, EscalationPolicy] = {}
        self.escalation_states: Dict[str, EscalationState] = {}  # alert_id -> EscalationState
        self.logger = logging.getLogger("AlertEscalationPolicy")

    def add_policy(self, policy: EscalationPolicy) -> None:
        """Add an escalation policy."""
        self.policies[policy.id] = policy
        self.logger.info(f"Added escalation policy: {policy.id}")

    def remove_policy(self, policy_id: str) -> bool:
        """Remove an escalation policy."""
        if policy_id in self.policies:
            del self.policies[policy_id]
            self.logger.info(f"Removed escalation policy: {policy_id}")
            return True
        return False

    def get_policy(self, policy_id: str) -> Optional[EscalationPolicy]:
        """Get an escalation policy by ID."""
        return self.policies.get(policy_id)

    def list_policies(self) -> List[EscalationPolicy]:
        """List all escalation policies."""
        return list(self.policies.values())

    def start_escalation(
        self,
        alert_id: str,
        policy_id: Optional[str] = None,
        path_id: Optional[str] = None,
    ) -> Optional[EscalationState]:
        """
        Start escalation for an alert.

        Args:
            alert_id: ID of the alert to escalate.
            policy_id: ID of the policy to use (uses default if not specified).
            path_id: ID of the path to use (uses default if not specified).

        Returns:
            EscalationState if escalation was started, None otherwise.
        """
        # If no policy specified, use the default policy
        if not policy_id:
            if not self.policies:
                return None
            policy = next(iter(self.policies.values()))
        else:
            policy = self.policies.get(policy_id)
            if not policy:
                return None

        # Determine the path to use
        if not path_id:
            path_id = policy.default_path

        path = policy.paths.get(path_id)
        if not path:
            return None

        # Create escalation state
        state = EscalationState(
            alert_id=alert_id,
            policy_id=policy.id,
            path_id=path_id,
            current_level=path.levels[0] if path.levels else EscalationLevel.LEVEL_1,
            status=EscalationStatus.PENDING,
            created_at=time.time(),
            updated_at=time.time(),
        )

        self.escalation_states[alert_id] = state
        self.logger.info(f"Started escalation for alert {alert_id} using path {path_id}")

        # Execute initial level actions
        self._execute_level_actions(alert_id)

        return state

    def check_escalation(self, alert_id: str, alert_data: Dict[str, Any]) -> List[EscalationAction]:
        """
        Check if an alert needs to be escalated further.

        Args:
            alert_id: ID of the alert to check.
            alert_data: Current alert data.

        Returns:
            List of actions to take for escalation.
        """
        state = self.escalation_states.get(alert_id)
        if not state:
            return []

        policy = self.policies.get(state.policy_id)
        if not policy:
            return []

        path = policy.paths.get(state.path_id)
        if not path:
            return []

        actions = []

        # Check if we need to escalate to the next level
        current_index = path.levels.index(state.current_level) if state.current_level in path.levels else -1
        next_index = current_index + 1

        if next_index < len(path.levels):
            next_level = path.levels[next_index]

            # Check triggers for escalation
            for trigger in path.triggers:
                if self._should_escalate(state, trigger, alert_data):
                    # Escalate to next level
                    state.current_level = next_level
                    state.updated_at = time.time()
                    state.escalation_times[next_level.value] = time.time()
                    state.status = EscalationStatus.ESCALATED

                    # Execute actions for the new level
                    actions.extend(self._get_level_actions(path, next_level))
                    self.logger.info(f"Escalated alert {alert_id} to level {next_level.value}")
                    break

        return actions

    def _should_escalate(
        self,
        state: EscalationState,
        trigger: EscalationTrigger,
        alert_data: Dict[str, Any],
    ) -> bool:
        """Check if an alert should be escalated based on a trigger."""
        if trigger == EscalationTrigger.MANUAL:
            return False  # Manual triggers are handled separately

        if trigger == EscalationTrigger.TIME_BASED:
            # Check if enough time has passed since the last escalation
            last_time = state.escalation_times.get(state.current_level.value, state.created_at)
            # Default to 1 hour for time-based escalation (configurable in path.conditions)
            required_time = state.path_id.conditions.get("escalation_time", 3600.0)
            return (time.time() - last_time) >= required_time

        if trigger == EscalationTrigger.SEVERITY_BASED:
            # Check if alert severity meets the threshold
            severity = alert_data.get("severity", "").lower()
            required_severity = state.path_id.conditions.get("min_severity", "").lower()
            severity_order = ["info", "low", "medium", "high", "critical"]
            if required_severity:
                return severity_order.index(severity) >= severity_order.index(required_severity)
            return False

        if trigger == EscalationTrigger.COUNT_BASED:
            # Check if alert has occurred enough times
            count = alert_data.get("occurrence_count", 0)
            required_count = state.path_id.conditions.get("min_occurrences", 1)
            return count >= required_count

        return False

    def _get_level_actions(self, path: EscalationPath, level: EscalationLevel) -> List[EscalationAction]:
        """Get actions for a specific escalation level."""
        # In a real implementation, this would be stored in the path configuration
        # For now, return some default actions based on level
        actions = []

        if level == EscalationLevel.LEVEL_1:
            actions.append(EscalationAction(
                action_type="notify",
                target="email",
                parameters={"recipients": ["team@company.com"]},
            ))
        elif level == EscalationLevel.LEVEL_2:
            actions.append(EscalationAction(
                action_type="notify",
                target="slack",
                parameters={"channel": "#alerts"},
            ))
            actions.append(EscalationAction(
                action_type="notify",
                target="sms",
                parameters={"recipients": ["+1234567890"]},
            ))
        elif level == EscalationLevel.LEVEL_3:
            actions.append(EscalationAction(
                action_type="notify",
                target="email",
                parameters={"recipients": ["management@company.com"]},
            ))
            actions.append(EscalationAction(
                action_type="create_ticket",
                target="jira",
                parameters={"project": "OPS", "priority": "high"},
            ))
        elif level == EscalationLevel.LEVEL_4:
            actions.append(EscalationAction(
                action_type="notify",
                target="pagerduty",
                parameters={"severity": "critical"},
            ))
        elif level == EscalationLevel.LEVEL_5:
            actions.append(EscalationAction(
                action_type="run_script",
                target="/path/to/emergency_script.sh",
                parameters={},
            ))

        return actions

    def _execute_level_actions(self, alert_id: str) -> List[Tuple[EscalationAction, bool]]:
        """Execute actions for the current escalation level."""
        state = self.escalation_states.get(alert_id)
        if not state:
            return []

        policy = self.policies.get(state.policy_id)
        if not policy:
            return []

        path = policy.paths.get(state.path_id)
        if not path:
            return []

        actions = self._get_level_actions(path, state.current_level)
        results = []

        for action in actions:
            try:
                # In a real implementation, this would execute the actual action
                # For now, just log and mark as successful
                success = self._execute_action(action, alert_id)
                results.append((action, success))
                state.actions_taken.append((action.action_type, time.time(), success))
            except Exception as e:
                self.logger.error(f"Error executing escalation action for alert {alert_id}: {e}")
                results.append((action, False))
                state.actions_taken.append((action.action_type, time.time(), False))

        return results

    def _execute_action(self, action: EscalationAction, alert_id: str) -> bool:
        """Execute a single escalation action."""
        self.logger.info(f"Executing escalation action: {action.action_type} for alert {alert_id}")
        # Placeholder: implement actual action execution
        return True

    def get_escalation_state(self, alert_id: str) -> Optional[EscalationState]:
        """Get the escalation state for an alert."""
        return self.escalation_states.get(alert_id)

    def cancel_escalation(self, alert_id: str) -> bool:
        """Cancel escalation for an alert."""
        state = self.escalation_states.get(alert_id)
        if not state:
            return False

        state.status = EscalationStatus.CANCELLED
        state.updated_at = time.time()
        self.logger.info(f"Cancelled escalation for alert {alert_id}")
        return True

    def resolve_escalation(self, alert_id: str) -> bool:
        """Mark an escalation as resolved."""
        state = self.escalation_states.get(alert_id)
        if not state:
            return False

        state.status = EscalationStatus.RESOLVED
        state.updated_at = time.time()
        self.logger.info(f"Resolved escalation for alert {alert_id}")
        return True

    def cleanup_escalations(self, max_age_seconds: float = 86400.0) -> int:
        """
        Clean up old escalation states.

        Args:
            max_age_seconds: Maximum age of escalation states to keep (default: 24 hours).

        Returns:
            Number of escalation states cleaned up.
        """
        cutoff = time.time() - max_age_seconds
        cleaned = 0

        to_remove = [
            alert_id for alert_id, state in self.escalation_states.items()
            if state.updated_at < cutoff and state.status in [EscalationStatus.RESOLVED, EscalationStatus.CANCELLED]
        ]

        for alert_id in to_remove:
            del self.escalation_states[alert_id]
            cleaned += 1

        self.logger.info(f"Cleaned up {cleaned} old escalation states")
        return cleaned

    def get_stats(self) -> Dict[str, Any]:
        """Get escalation policy statistics."""
        active_escalations = sum(
            1 for s in self.escalation_states.values()
            if s.status in [EscalationStatus.PENDING, EscalationStatus.ESCALATED]
        )

        return {
            "total_policies": len(self.policies),
            "enabled_policies": sum(1 for p in self.policies.values() if p.enabled),
            "active_escalations": active_escalations,
            "total_escalations": len(self.escalation_states),
            "by_status": {
                s.value: sum(1 for e in self.escalation_states.values() if e.status == s)
                for s in EscalationStatus
            },
        }
