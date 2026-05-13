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
Pillar 4: Real-Time Monitoring & Alerting System - Alert Rules Engine

Rule-based alert configuration and conditional alert triggering.
"""

import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Union, Tuple
from enum import Enum
import logging
import operator


class RuleConditionType(Enum):
    FIELD_COMPARISON = "field_comparison"
    THRESHOLD = "threshold"
    REGEX = "regex"
    IN_LIST = "in_list"
    NOT_IN_LIST = "not_in_list"
    TIME_BASED = "time_based"
    BOOLEAN = "boolean"
    CUSTOM = "custom"


class RuleOperator(Enum):
    EQUAL = "=="
    NOT_EQUAL = "!="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"  # regex
    IN = "in"
    NOT_IN = "not_in"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"


@dataclass
class RuleCondition:
    """A single condition in an alert rule."""
    type: RuleConditionType
    field: str
    operator: RuleOperator
    value: Any
    negate: bool = False

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluate this condition against data."""
        try:
            if self.type == RuleConditionType.FIELD_COMPARISON:
                if self.field not in data:
                    return False

                data_value = data[self.field]
                op = self._get_operator(self.operator)

                if op == operator.contains:
                    result = self.value in data_value
                elif op == operator.not_contains:
                    result = self.value not in data_value
                elif op == operator.matches:
                    if isinstance(data_value, str):
                        result = bool(re.search(str(self.value), data_value))
                    else:
                        result = False
                elif op == operator.in_:
                    result = data_value in self.value
                elif op == operator.not_in:
                    result = data_value not in self.value
                elif op == operator.is_:
                    result = data_value is self.value
                elif op == operator.is_not:
                    result = data_value is not self.value
                else:
                    result = op(data_value, self.value)

                return not result if self.negate else result

            elif self.type == RuleConditionType.THRESHOLD:
                if self.field not in data:
                    return False

                data_value = data[self.field]
                if not isinstance(data_value, (int, float)):
                    return False

                if self.operator == RuleOperator.GREATER_THAN:
                    result = data_value > self.value
                elif self.operator == RuleOperator.GREATER_THAN_OR_EQUAL:
                    result = data_value >= self.value
                elif self.operator == RuleOperator.LESS_THAN:
                    result = data_value < self.value
                elif self.operator == RuleOperator.LESS_THAN_OR_EQUAL:
                    result = data_value <= self.value
                else:
                    result = False

                return not result if self.negate else result

            elif self.type == RuleConditionType.REGEX:
                if self.field not in data:
                    return False

                data_value = data[self.field]
                if not isinstance(data_value, str):
                    return False

                result = bool(re.search(str(self.value), data_value))
                return not result if self.negate else result

            elif self.type == RuleConditionType.IN_LIST:
                if self.field not in data:
                    return False

                result = data[self.field] in self.value
                return not result if self.negate else result

            elif self.type == RuleConditionType.NOT_IN_LIST:
                if self.field not in data:
                    return False

                result = data[self.field] not in self.value
                return not result if self.negate else result

            elif self.type == RuleConditionType.TIME_BASED:
                current_time = time.time()
                if self.operator == RuleOperator.GREATER_THAN:
                    result = current_time > self.value
                elif self.operator == RuleOperator.LESS_THAN:
                    result = current_time < self.value
                else:
                    result = False

                return not result if self.negate else result

            elif self.type == RuleConditionType.BOOLEAN:
                if self.field not in data:
                    return False

                data_value = data[self.field]
                if self.operator == RuleOperator.IS_TRUE:
                    result = bool(data_value)
                elif self.operator == RuleOperator.IS_FALSE:
                    result = not bool(data_value)
                else:
                    result = False

                return not result if self.negate else result

            elif self.type == RuleConditionType.CUSTOM:
                if not callable(self.value):
                    return False

                result = bool(self.value(data))
                return not result if self.negate else result

            return False

        except Exception:
            return False

    def _get_operator(self, op: RuleOperator) -> Callable:
        """Get the operator function for a RuleOperator."""
        op_map = {
            RuleOperator.EQUAL: operator.eq,
            RuleOperator.NOT_EQUAL: operator.ne,
            RuleOperator.GREATER_THAN: operator.gt,
            RuleOperator.GREATER_THAN_OR_EQUAL: operator.ge,
            RuleOperator.LESS_THAN: operator.lt,
            RuleOperator.LESS_THAN_OR_EQUAL: operator.le,
            RuleOperator.CONTAINS: operator.contains,
            RuleOperator.NOT_CONTAINS: operator.not_contains,
            RuleOperator.IN: operator.contains,  # For "in" operator
            RuleOperator.NOT_IN: lambda a, b: a not in b,
            RuleOperator.MATCHES: lambda a, b: bool(re.search(b, a)) if isinstance(a, str) else False,
        }
        return op_map.get(op, operator.eq)


class RuleLogic(Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


@dataclass
class RuleGroup:
    """A group of conditions with a logical operator."""
    logic: RuleLogic
    conditions: List[Union[RuleCondition, "RuleGroup"]] = field(default_factory=list)

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluate this group of conditions."""
        if self.logic == RuleLogic.AND:
            return all(c.evaluate(data) for c in self.conditions)
        elif self.logic == RuleLogic.OR:
            return any(c.evaluate(data) for c in self.conditions)
        elif self.logic == RuleLogic.NOT:
            if len(self.conditions) != 1:
                return False
            return not self.conditions[0].evaluate(data)
        return False


@dataclass
class AlertRule:
    """An alert rule with conditions and actions."""
    id: str
    name: str
    description: str
    enabled: bool = True
    severity: str = "medium"  # low, medium, high, critical
    type: str = "custom"
    tags: List[str] = field(default_factory=list)
    condition: Union[RuleCondition, RuleGroup, None] = None
    conditions: List[Union[RuleCondition, RuleGroup]] = field(default_factory=list)
    action: Optional[Callable] = None
    cooldown_period: float = 300.0  # 5 minutes
    last_triggered: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluate this rule against data."""
        if not self.enabled:
            return False

        # Check cooldown
        if time.time() - self.last_triggered < self.cooldown_period:
            return False

        if self.condition:
            return self.condition.evaluate(data)

        if self.conditions:
            if len(self.conditions) == 1:
                return self.conditions[0].evaluate(data)
            else:
                # Default to AND logic for multiple conditions
                return all(c.evaluate(data) for c in self.conditions)

        return False

    def trigger(self, data: Dict[str, Any]) -> Any:
        """Trigger the rule's action."""
        self.last_triggered = time.time()
        if self.action and callable(self.action):
            return self.action(data)
        return None


class AlertRuleEngine:
    """
    Rule-based alert configuration engine with support for:
    - Conditional alert triggering
    - Threshold-based alerts
    - Multi-condition alert rules
    - Cooldown periods to prevent alert spam
    """

    def __init__(self):
        """Initialize the alert rule engine."""
        self.rules: Dict[str, AlertRule] = {}
        self.logger = logging.getLogger("AlertRuleEngine")

    def add_rule(self, rule: AlertRule) -> None:
        """Add a rule to the engine."""
        self.rules[rule.id] = rule
        self.logger.info(f"Added rule: {rule.id}")

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule from the engine."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            self.logger.info(f"Removed rule: {rule_id}")
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """Get a rule by ID."""
        return self.rules.get(rule_id)

    def list_rules(self) -> List[AlertRule]:
        """List all rules."""
        return list(self.rules.values())

    def evaluate_all(self, data: Dict[str, Any]) -> List[Tuple[AlertRule, Any]]:
        """
        Evaluate all rules against the given data.

        Args:
            data: Data to evaluate against rules.

        Returns:
            List of tuples (rule, action_result) for triggered rules.
        """
        triggered = []

        for rule in self.rules.values():
            if rule.evaluate(data):
                try:
                    result = rule.trigger(data)
                    triggered.append((rule, result))
                    self.logger.info(f"Rule {rule.id} triggered: {rule.name}")
                except Exception as e:
                    self.logger.error(f"Error triggering rule {rule.id}: {e}")

        return triggered

    def evaluate_by_tag(self, data: Dict[str, Any], tags: List[str]) -> List[Tuple[AlertRule, Any]]:
        """
        Evaluate rules matching specific tags.

        Args:
            data: Data to evaluate.
            tags: Tags to match.

        Returns:
            List of tuples (rule, action_result) for triggered rules.
        """
        triggered = []
        tag_set = set(tags)

        for rule in self.rules.values():
            if not rule.enabled:
                continue

            rule_tags = set(rule.tags)
            if not rule_tags or rule_tags & tag_set:
                if rule.evaluate(data):
                    try:
                        result = rule.trigger(data)
                        triggered.append((rule, result))
                    except Exception as e:
                        self.logger.error(f"Error triggering rule {rule.id}: {e}")

        return triggered

    def create_rule_from_config(self, config: Dict[str, Any]) -> AlertRule:
        """
        Create an AlertRule from a configuration dictionary.

        Args:
            config: Rule configuration.

        Returns:
            AlertRule instance.
        """
        rule_id = config.get("id", "")
        name = config.get("name", "Unnamed Rule")
        description = config.get("description", "")
        enabled = config.get("enabled", True)
        severity = config.get("severity", "medium")
        rule_type = config.get("type", "custom")
        tags = config.get("tags", [])
        cooldown = config.get("cooldown_period", 300.0)
        metadata = config.get("metadata", {})

        # Parse conditions
        conditions_config = config.get("conditions", [])
        conditions = []

        for cond_config in conditions_config:
            if isinstance(cond_config, dict):
                cond_type = cond_config.get("type", RuleConditionType.FIELD_COMPARISON.value)
                field = cond_config.get("field", "")
                op = cond_config.get("operator", RuleOperator.EQUAL.value)
                value = cond_config.get("value")
                negate = cond_config.get("negate", False)

                try:
                    cond_type_enum = RuleConditionType(cond_type)
                    op_enum = RuleOperator(op)
                    condition = RuleCondition(
                        type=cond_type_enum,
                        field=field,
                        operator=op_enum,
                        value=value,
                        negate=negate,
                    )
                    conditions.append(condition)
                except ValueError as e:
                    self.logger.warning(f"Invalid condition in rule {rule_id}: {e}")

        # Handle groups (simplified - for complex rules, use RuleGroup)
        # For now, we'll just use the conditions list

        return AlertRule(
            id=rule_id,
            name=name,
            description=description,
            enabled=enabled,
            severity=severity,
            type=rule_type,
            tags=tags,
            conditions=conditions,
            cooldown_period=cooldown,
            metadata=metadata,
        )

    def load_rules_from_config(self, config: List[Dict[str, Any]]) -> None:
        """
        Load multiple rules from a configuration list.

        Args:
            config: List of rule configurations.
        """
        for rule_config in config:
            rule = self.create_rule_from_config(rule_config)
            self.add_rule(rule)

    def get_stats(self) -> Dict[str, Any]:
        """Get rule engine statistics."""
        return {
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules.values() if r.enabled),
            "by_severity": {
                "low": sum(1 for r in self.rules.values() if r.severity == "low"),
                "medium": sum(1 for r in self.rules.values() if r.severity == "medium"),
                "high": sum(1 for r in self.rules.values() if r.severity == "high"),
                "critical": sum(1 for r in self.rules.values() if r.severity == "critical"),
            },
        }

    def reset_rule_cooldown(self, rule_id: str) -> bool:
        """Reset the cooldown for a rule."""
        if rule_id in self.rules:
            self.rules[rule_id].last_triggered = 0.0
            return True
        return False
