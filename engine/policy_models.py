"""Pydantic models for YAML-defined policy rules."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ConfidenceRule(BaseModel):
    when: Optional[str] = None
    default: Optional[float] = None
    score: Optional[float] = None


class UrgencyRule(BaseModel):
    when: Optional[str] = None
    default: Optional[str] = None
    urgency: Optional[str] = None


class PolicyRule(BaseModel):
    id: str
    scope: str
    condition: str
    evidence_sources: List[str] = Field(default_factory=list)
    urgency: Optional[str] = None
    urgency_rules: Optional[List[UrgencyRule]] = None
    confidence_score: Optional[float] = None
    confidence_reason: Optional[str] = None
    confidence_reason_template: Optional[str] = None
    confidence_rules: Optional[List[ConfidenceRule]] = None
    thresholds: Optional[Dict[str, Any]] = None

    def get_confidence(self, **context) -> float:
        """Return the confidence score, evaluating rules against context if present."""
        if self.confidence_rules:
            for rule in self.confidence_rules:
                if rule.default is not None:
                    continue
                if rule.when and rule.score is not None:
                    if _eval_simple_condition(rule.when, context):
                        return rule.score
            for rule in self.confidence_rules:
                if rule.default is not None:
                    return rule.default
        return self.confidence_score or 0.5

    def get_urgency(self, **context) -> str:
        """Return the urgency level, evaluating rules against context if present."""
        if self.urgency_rules:
            for rule in self.urgency_rules:
                if rule.default is not None:
                    continue
                if rule.when and rule.urgency:
                    if _eval_simple_condition(rule.when, context):
                        return rule.urgency
            for rule in self.urgency_rules:
                if rule.default is not None:
                    return rule.default
        return self.urgency or "medium"


class PolicyRuleSet(BaseModel):
    version: str = "1.0"
    constraint_to_stage: Dict[str, str] = Field(default_factory=dict)
    rules: List[PolicyRule] = Field(default_factory=list)


def _eval_simple_condition(condition: str, context: Dict[str, Any]) -> bool:
    """Evaluate a simple threshold condition like 'avg_cpu >= 80' against context."""
    condition = condition.strip()
    for op_str, op_func in [
        (">=", lambda a, b: a >= b),
        ("<=", lambda a, b: a <= b),
        ("==", lambda a, b: a == b),
        ("!=", lambda a, b: a != b),
        (">", lambda a, b: a > b),
        ("<", lambda a, b: a < b),
    ]:
        if op_str in condition:
            parts = condition.split(op_str, 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val_str = parts[1].strip()
                actual = context.get(key)
                if actual is None:
                    return False
                try:
                    expected = type(actual)(val_str)
                    return op_func(actual, expected)
                except (ValueError, TypeError):
                    return False
    if condition == "has_summit_days":
        return bool(context.get("has_summit_days"))
    return False
