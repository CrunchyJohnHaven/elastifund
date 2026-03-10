"""Promotion and demotion policy for the flywheel control plane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data_layer.schema import DailySnapshot

ENV_LADDER = ("sim", "paper", "shadow", "micro_live", "scaled_live", "core_live")

# Lane-level kill registry.  Lanes listed here are permanently blocked from
# receiving new capital or progressing beyond their current stage.  Existing
# positions are held to settlement only.
#
# Format: {lane_id: kill_reason}
KILLED_LANES: dict[str, str] = {
    "kalshi_weather_bracket": (
        "Killed 2026-03-11. Model accuracy 27-35% vs NWS settlement, "
        "forecast precision 15x too imprecise, negative EV at realistic entry. "
        "Successor: binary_daily_weather (paper-only until 4 evidence gates pass)."
    ),
}


@dataclass(frozen=True)
class PolicyOutcome:
    """Machine-readable result of evaluating one deployment snapshot."""

    decision: str
    from_stage: str
    to_stage: str
    reason_code: str
    notes: str
    priority: int
    metrics: dict[str, Any]


@dataclass(frozen=True)
class PromotionRule:
    """Thresholds required to move beyond one stage."""

    min_closed_trades: int
    min_win_rate: float
    max_drawdown_pct: float
    max_brier: float
    min_fill_rate: float | None = None
    max_slippage_bps: float | None = None


PROMOTION_RULES: dict[str, PromotionRule] = {
    "sim": PromotionRule(
        min_closed_trades=5,
        min_win_rate=0.55,
        max_drawdown_pct=0.20,
        max_brier=0.24,
    ),
    "paper": PromotionRule(
        min_closed_trades=20,
        min_win_rate=0.55,
        max_drawdown_pct=0.20,
        max_brier=0.24,
    ),
    "shadow": PromotionRule(
        min_closed_trades=10,
        min_win_rate=0.55,
        max_drawdown_pct=0.15,
        max_brier=0.25,
        min_fill_rate=0.50,
        max_slippage_bps=30.0,
    ),
    "micro_live": PromotionRule(
        min_closed_trades=20,
        min_win_rate=0.55,
        max_drawdown_pct=0.15,
        max_brier=0.25,
        min_fill_rate=0.65,
        max_slippage_bps=20.0,
    ),
    "scaled_live": PromotionRule(
        min_closed_trades=30,
        min_win_rate=0.58,
        max_drawdown_pct=0.12,
        max_brier=0.24,
        min_fill_rate=0.70,
        max_slippage_bps=15.0,
    ),
}


def _next_stage(stage: str) -> str:
    idx = ENV_LADDER.index(stage)
    return ENV_LADDER[min(idx + 1, len(ENV_LADDER) - 1)]


def _previous_stage(stage: str) -> str:
    idx = ENV_LADDER.index(stage)
    return ENV_LADDER[max(idx - 1, 0)]


def _metrics(snapshot: DailySnapshot) -> dict[str, Any]:
    metadata = snapshot.metrics if isinstance(snapshot.metrics, dict) else {}
    return {
        "snapshot_date": snapshot.snapshot_date,
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "closed_trades": snapshot.closed_trades,
        "open_positions": snapshot.open_positions,
        "win_rate": snapshot.win_rate,
        "fill_rate": snapshot.fill_rate,
        "avg_slippage_bps": snapshot.avg_slippage_bps,
        "rolling_brier": snapshot.rolling_brier,
        "rolling_ece": snapshot.rolling_ece,
        "max_drawdown_pct": snapshot.max_drawdown_pct,
        "kill_events": snapshot.kill_events,
        "control_context": metadata.get("control_context") if isinstance(metadata.get("control_context"), dict) else metadata,
        "candidate_source": str(metadata.get("candidate_source") or "").strip().lower(),
        "comparison_only": bool(metadata.get("comparison_only")),
        "stale_reasons": metadata.get("stale_reasons"),
        "packet_age_minutes": metadata.get("packet_age_minutes"),
        "openclaw_age_minutes": metadata.get("openclaw_age_minutes"),
        "expected_arr_delta": metadata.get("expected_arr_delta"),
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_lane_killed(lane_id: str) -> bool:
    """Return True if the lane is in the permanent kill registry."""
    return lane_id in KILLED_LANES


def evaluate_snapshot(snapshot: DailySnapshot) -> PolicyOutcome:
    """Evaluate one latest snapshot and emit a control-plane action."""

    stage = snapshot.environment
    metrics = _metrics(snapshot)

    # Check lane-level kill registry before any other evaluation.
    lane_id = str(metrics.get("candidate_source") or "").strip().lower()
    if lane_id in KILLED_LANES:
        return PolicyOutcome(
            decision="hold",
            from_stage=stage,
            to_stage=stage,
            reason_code="lane_killed",
            notes=KILLED_LANES[lane_id],
            priority=100,
            metrics=metrics,
        )

    candidate_source = str(metrics.get("candidate_source") or "").strip().lower()
    control_context = metrics.get("control_context")
    if isinstance(control_context, dict):
        stale_reasons = [str(item).strip() for item in control_context.get("stale_reasons", []) if str(item).strip()]
        if bool(control_context.get("read_only")) or stale_reasons:
            return PolicyOutcome(
                decision="hold",
                from_stage=stage,
                to_stage=stage,
                reason_code="stale_inputs_blocked",
                notes="Control-context refresh is stale or blocked; waiting for fresh pipeline data.",
                priority=95,
                metrics=metrics,
            )

        candidate_reasons = [str(item).strip() for item in (metrics.get("stale_reasons") or []) if str(item).strip()]
        if candidate_reasons:
            return PolicyOutcome(
                decision="hold",
                from_stage=stage,
                to_stage=stage,
                reason_code="candidate_stale_reasons",
                notes="Candidate carries explicit staleness or freshness blockers.",
                priority=94,
                metrics=metrics,
            )

        if candidate_source == "openclaw":
            packet_age = _safe_float(metrics.get("packet_age_minutes"))
            openclaw_limit = _safe_float(control_context.get("openclaw_data_age_minutes"))
            if packet_age is None:
                return PolicyOutcome(
                    decision="hold",
                    from_stage=stage,
                    to_stage=stage,
                    reason_code="openclaw_packet_age_missing",
                    notes="OpenClaw candidate has no packet timestamp and cannot be promoted while stale gating is active.",
                    priority=93,
                    metrics=metrics,
                )
            if openclaw_limit is not None and packet_age > openclaw_limit:
                return PolicyOutcome(
                    decision="hold",
                    from_stage=stage,
                    to_stage=stage,
                    reason_code="openclaw_packet_stale",
                    notes="OpenClaw packet age exceeds max age threshold.",
                    priority=93,
                    metrics=metrics,
                )

            openclaw_age = _safe_float(metrics.get("openclaw_age_minutes"))
            if openclaw_age is not None and openclaw_limit is not None and openclaw_age > openclaw_limit:
                return PolicyOutcome(
                    decision="hold",
                    from_stage=stage,
                    to_stage=stage,
                    reason_code="openclaw_evidence_stale",
                    notes="OpenClaw freshness telemetry is stale versus configured threshold.",
                    priority=93,
                    metrics=metrics,
                )

        min_arr_bps = float(control_context.get("max_arr_improvement_bps") or 0.0)
        expected_arr_delta = metrics.get("expected_arr_delta")
        try:
            expected_arr_delta_value = float(expected_arr_delta) if expected_arr_delta is not None else None
        except (TypeError, ValueError):
            expected_arr_delta_value = None
        if candidate_source == "openclaw" and expected_arr_delta_value is not None and min_arr_bps > 0 and expected_arr_delta_value < min_arr_bps:
            return PolicyOutcome(
                decision="hold",
                from_stage=stage,
                to_stage=stage,
                reason_code="arr_improvement_below_min",
                notes="Expected ARR uplift is below policy minimum.",
                priority=90,
                metrics=metrics,
            )

    if stage == "core_live":
        return PolicyOutcome(
            decision="hold",
            from_stage=stage,
            to_stage=stage,
            reason_code="manual_gate_core_live",
            notes="Core live promotion remains outside the MVP automation boundary.",
            priority=95,
            metrics=metrics,
        )

    if snapshot.kill_events > 0:
        return PolicyOutcome(
            decision="kill",
            from_stage=stage,
            to_stage=stage,
            reason_code="kill_events_present",
            notes="Kill events were recorded during the latest window.",
            priority=100,
            metrics=metrics,
        )

    rule = PROMOTION_RULES[stage]

    if snapshot.max_drawdown_pct > rule.max_drawdown_pct:
        decision = "demote" if stage in {"micro_live", "scaled_live"} else "kill"
        target = _previous_stage(stage) if decision == "demote" else stage
        return PolicyOutcome(
            decision=decision,
            from_stage=stage,
            to_stage=target,
            reason_code="drawdown_breach",
            notes="Drawdown exceeded the policy limit for this stage.",
            priority=95,
            metrics=metrics,
        )

    if snapshot.rolling_brier is not None and snapshot.rolling_brier > rule.max_brier:
        decision = "demote" if stage in {"micro_live", "scaled_live"} else "hold"
        target = _previous_stage(stage) if decision == "demote" else stage
        return PolicyOutcome(
            decision=decision,
            from_stage=stage,
            to_stage=target,
            reason_code="calibration_drift",
            notes="Rolling Brier score breached the allowed bound for this stage.",
            priority=85,
            metrics=metrics,
        )

    if snapshot.closed_trades < rule.min_closed_trades:
        return PolicyOutcome(
            decision="hold",
            from_stage=stage,
            to_stage=stage,
            reason_code="insufficient_evidence",
            notes="Collect more closed trades before promoting the strategy.",
            priority=40,
            metrics=metrics,
        )

    if snapshot.realized_pnl <= 0:
        decision = "demote" if stage in {"micro_live", "scaled_live"} else "hold"
        target = _previous_stage(stage) if decision == "demote" else stage
        return PolicyOutcome(
            decision=decision,
            from_stage=stage,
            to_stage=target,
            reason_code="negative_realized_pnl",
            notes="Latest realized PnL is non-positive after the minimum sample threshold.",
            priority=90 if decision == "demote" else 60,
            metrics=metrics,
        )

    if snapshot.win_rate is not None and snapshot.win_rate < rule.min_win_rate:
        decision = "demote" if stage in {"micro_live", "scaled_live"} else "hold"
        target = _previous_stage(stage) if decision == "demote" else stage
        return PolicyOutcome(
            decision=decision,
            from_stage=stage,
            to_stage=target,
            reason_code="win_rate_below_gate",
            notes="Win rate fell below the promotion threshold.",
            priority=80,
            metrics=metrics,
        )

    if rule.min_fill_rate is not None:
        fill_rate = snapshot.fill_rate or 0.0
        if fill_rate < rule.min_fill_rate:
            decision = "demote" if stage in {"micro_live", "scaled_live"} else "hold"
            target = _previous_stage(stage) if decision == "demote" else stage
            return PolicyOutcome(
                decision=decision,
                from_stage=stage,
                to_stage=target,
                reason_code="fill_rate_below_gate",
                notes="Execution fill rate is too low to justify progression.",
                priority=80,
                metrics=metrics,
            )

    if rule.max_slippage_bps is not None:
        slippage = snapshot.avg_slippage_bps or 0.0
        if slippage > rule.max_slippage_bps:
            decision = "demote" if stage in {"micro_live", "scaled_live"} else "hold"
            target = _previous_stage(stage) if decision == "demote" else stage
            return PolicyOutcome(
                decision=decision,
                from_stage=stage,
                to_stage=target,
                reason_code="slippage_above_gate",
                notes="Execution slippage is above the allowed threshold.",
                priority=75,
                metrics=metrics,
            )

    next_stage = _next_stage(stage)
    if next_stage == "core_live":
        return PolicyOutcome(
            decision="hold",
            from_stage=stage,
            to_stage=stage,
            reason_code="manual_gate_core_live",
            notes="The strategy is eligible for review but not for automatic promotion to core live.",
            priority=90,
            metrics=metrics,
        )

    return PolicyOutcome(
        decision="promote",
        from_stage=stage,
        to_stage=next_stage,
        reason_code="promotion_policy_pass",
        notes="All promotion rules passed for the current stage.",
        priority=70,
        metrics=metrics,
    )
