"""Structured findings and task-routing helpers for the flywheel control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from data_layer import crud


LESSON_BY_REASON: dict[str, str] = {
    "promotion_policy_pass": "Promotion requires passing explicit stage gates, not narrative optimism.",
    "insufficient_evidence": "Do not promote before the minimum evidence threshold is met.",
    "negative_realized_pnl": "Positive realized PnL is a hard progression gate once sample size is large enough.",
    "win_rate_below_gate": "Directional accuracy is a deployability constraint, not a vanity metric.",
    "fill_rate_below_gate": "Execution quality must be treated as a first-class promotion signal.",
    "slippage_above_gate": "Nominal edge is invalid if execution slippage consumes it.",
    "calibration_drift": "Forecast drift must trigger recalibration before further promotion.",
    "drawdown_breach": "Drawdown is a control-plane signal to reduce scope or demote exposure.",
    "kill_events_present": "Kill-switch activity should feed straight into strategy termination or review.",
    "manual_gate_core_live": "Core-live progression remains a supervised boundary even in autonomous loops.",
    "activity_anomaly": "Runtime anomalies should create directed review work instead of silent pauses.",
}


@dataclass(frozen=True)
class FindingSpec:
    finding_key: str
    cycle_id: int | None
    strategy_version_id: int | None
    lane: str | None
    environment: str | None
    source_kind: str
    finding_type: str
    title: str
    summary: str
    lesson: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    confidence: float | None = None
    status: str = "open"


@dataclass(frozen=True)
class TaskSpec:
    cycle_id: int
    strategy_version_id: int | None
    action: str
    title: str
    details: str | None = None
    priority: int = 50
    status: str = "open"
    lane: str | None = None
    environment: str | None = None
    source_kind: str | None = None
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def lesson_for_reason(reason_code: str, *, default: str | None = None) -> str | None:
    if reason_code in LESSON_BY_REASON:
        return LESSON_BY_REASON[reason_code]
    return default


def record_finding(session: Session, spec: FindingSpec):
    return crud.get_or_create_flywheel_finding(
        session,
        finding_key=spec.finding_key,
        cycle_id=spec.cycle_id,
        strategy_version_id=spec.strategy_version_id,
        lane=spec.lane,
        environment=spec.environment,
        source_kind=spec.source_kind,
        finding_type=spec.finding_type,
        title=spec.title,
        summary=spec.summary,
        lesson=spec.lesson,
        evidence=spec.evidence,
        priority=spec.priority,
        confidence=spec.confidence,
        status=spec.status,
    )


def record_task(session: Session, spec: TaskSpec, *, finding_id: int | None = None):
    return crud.create_flywheel_task(
        session,
        cycle_id=spec.cycle_id,
        strategy_version_id=spec.strategy_version_id,
        finding_id=finding_id,
        action=spec.action,
        title=spec.title,
        details=spec.details,
        priority=spec.priority,
        status=spec.status,
        lane=spec.lane,
        environment=spec.environment,
        source_kind=spec.source_kind,
        source_ref=spec.source_ref,
        metadata=spec.metadata,
    )


def record_finding_with_task(
    session: Session,
    *,
    finding: FindingSpec | None,
    task: TaskSpec,
):
    finding_row = record_finding(session, finding) if finding is not None else None
    task_row = record_task(
        session,
        task,
        finding_id=None if finding_row is None else finding_row.id,
    )
    return finding_row, task_row
