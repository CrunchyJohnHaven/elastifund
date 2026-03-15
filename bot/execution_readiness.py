#!/usr/bin/env python3
"""Execution-readiness gates for structural arbitrage lanes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
RESTART_WEEKDAY = 0  # Monday
RESTART_START_HOUR = 20
RESTART_START_MINUTE = 0
RESTART_DURATION_MINUTES = 20


def _as_utc_datetime(value: datetime | int | float | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def in_polymarket_restart_window(now: datetime | int | float | None = None) -> bool:
    """Return True during the documented weekly maintenance window.

    Official Polymarket docs currently describe the maintenance window as
    Monday 20:00-20:20 ET for order-related endpoints returning HTTP 425.
    """

    current = _as_utc_datetime(now).astimezone(EASTERN_TZ)
    if current.weekday() != RESTART_WEEKDAY:
        return False
    start_minutes = RESTART_START_HOUR * 60 + RESTART_START_MINUTE
    current_minutes = current.hour * 60 + current.minute
    return start_minutes <= current_minutes < (start_minutes + RESTART_DURATION_MINUTES)


def builder_relayer_available(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return bool(
        source.get("POLY_BUILDER_API_KEY")
        and source.get("POLY_BUILDER_API_SECRET")
        and source.get("POLY_BUILDER_API_PASSPHRASE")
    )


@dataclass(frozen=True)
class FeedHealth:
    healthy: bool
    reasons: tuple[str, ...]
    silence_seconds: float | None = None
    divergence_ticks: float | None = None


def evaluate_feed_health(
    *,
    last_data_ts: float | int | None,
    max_silence_seconds: float,
    now_ts: float | int | None = None,
    book_best_bid: float | None = None,
    book_best_ask: float | None = None,
    price_best_bid: float | None = None,
    price_best_ask: float | None = None,
    midpoint: float | None = None,
    tick_size: float | None = None,
    max_divergence_ticks: float = 1.0,
) -> FeedHealth:
    now_value = float(_as_utc_datetime(now_ts).timestamp())
    silence_seconds = None if last_data_ts is None else max(0.0, now_value - float(last_data_ts))
    reasons: list[str] = []

    if last_data_ts is None:
        reasons.append("feed_missing")
    elif silence_seconds is not None and silence_seconds > float(max_silence_seconds):
        reasons.append("feed_silent")

    divergence_ticks = None
    valid_book = (
        book_best_bid is not None
        and book_best_ask is not None
        and 0.0 <= float(book_best_bid) <= 1.0
        and 0.0 <= float(book_best_ask) <= 1.0
    )
    valid_price = (
        price_best_bid is not None
        and price_best_ask is not None
        and 0.0 <= float(price_best_bid) <= 1.0
        and 0.0 <= float(price_best_ask) <= 1.0
    )
    resolved_midpoint = None
    if midpoint is not None:
        resolved_midpoint = float(midpoint)
    elif valid_price:
        resolved_midpoint = (float(price_best_bid) + float(price_best_ask)) / 2.0

    if valid_book and resolved_midpoint is not None and tick_size is not None and tick_size > 0:
        book_midpoint = (float(book_best_bid) + float(book_best_ask)) / 2.0
        divergence_ticks = abs(book_midpoint - resolved_midpoint) / float(tick_size)
        if divergence_ticks > float(max_divergence_ticks):
            reasons.append("book_price_divergence")

    return FeedHealth(
        healthy=not reasons,
        reasons=tuple(reasons),
        silence_seconds=silence_seconds,
        divergence_ticks=divergence_ticks,
    )


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    status: str
    reasons: tuple[str, ...]
    estimated_one_leg_loss_usd: float


@dataclass(frozen=True)
class ExecutionReadinessInputs:
    feed_healthy: bool
    tick_size_ok: bool
    quote_surface_ok: bool
    estimated_one_leg_loss_usd: float
    max_one_leg_loss_threshold_usd: float
    neg_risk: bool
    neg_risk_flag_configured: bool
    builder_required: bool = False
    builder_available: bool = False
    now: datetime | int | float | None = None


RECOMMENDED_MODE_HOLD = "hold"
RECOMMENDED_MODE_PAPER = "paper"
RECOMMENDED_MODE_SHADOW = "shadow"


@dataclass(frozen=True)
class RestartRequiredArtifact:
    name: str
    path: str
    exists: bool


@dataclass(frozen=True)
class FastFlowRestartInputs:
    remote_cycle_status: dict[str, Any] | None
    remote_service_status: dict[str, Any] | None
    jj_state: dict[str, Any] | None
    root_test_status: dict[str, Any] | None
    required_artifacts: tuple[RestartRequiredArtifact, ...] = ()


@dataclass(frozen=True)
class FastFlowRestartDecision:
    restart_ready: bool
    blocked_reasons: tuple[str, ...]
    required_artifacts: tuple[RestartRequiredArtifact, ...]
    recommended_mode: str
    service_status: str
    cycles_completed: int
    root_tests_status: str
    wallet_ready: bool


LANE_STATUS_READY_FOR_SHADOW = "ready_for_shadow"
LANE_STATUS_READY_FOR_MICRO_LIVE = "ready_for_micro_live"
LANE_STATUS_BLOCKED = "blocked"


@dataclass(frozen=True)
class StructuralLaneReadinessInputs:
    lane: str
    maker_fill_proxy_rate: float | None = None
    maker_fill_wilson_lower: float | None = None
    violation_half_life_seconds: float | None = None
    settlement_evidence_count: int = 0
    classification_accuracy: float | None = None
    false_positive_rate: float | None = None
    public_a6_executable_count: int | None = None
    public_a6_threshold: float = 0.95
    public_b1_template_pair_count: int | None = None
    public_b1_market_sample_size: int = 1000
    minimum_fill_wilson_lower: float = 0.20
    minimum_violation_half_life_seconds: float = 10.0
    minimum_settlement_evidence_count: int = 3
    minimum_classification_accuracy: float = 0.85
    maximum_false_positive_rate: float = 0.05


@dataclass(frozen=True)
class StructuralLaneReadiness:
    lane: str
    status: str
    maker_fill_proxy_rate: float | None
    violation_half_life_seconds: float | None
    settlement_evidence_count: int
    classification_accuracy: float | None
    false_positive_rate: float | None
    blocked_reasons: tuple[str, ...]
    maker_fill_wilson_lower: float | None = None
    public_a6_executable_count: int | None = None
    public_a6_threshold: float | None = None
    public_b1_template_pair_count: int | None = None
    public_b1_market_sample_size: int | None = None


def _finalize_lane_status(
    inputs: StructuralLaneReadinessInputs,
    blocked_reasons: list[str],
    *,
    shadow_ready: bool,
    micro_live_ready: bool,
) -> StructuralLaneReadiness:
    if blocked_reasons:
        status = LANE_STATUS_BLOCKED
    elif micro_live_ready:
        status = LANE_STATUS_READY_FOR_MICRO_LIVE
    elif shadow_ready:
        status = LANE_STATUS_READY_FOR_SHADOW
    else:
        status = LANE_STATUS_BLOCKED
        blocked_reasons = ["status_resolution_failed"]

    return StructuralLaneReadiness(
        lane=str(inputs.lane),
        status=status,
        maker_fill_proxy_rate=inputs.maker_fill_proxy_rate,
        violation_half_life_seconds=inputs.violation_half_life_seconds,
        settlement_evidence_count=max(0, int(inputs.settlement_evidence_count)),
        classification_accuracy=inputs.classification_accuracy,
        false_positive_rate=inputs.false_positive_rate,
        blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
        maker_fill_wilson_lower=inputs.maker_fill_wilson_lower,
        public_a6_executable_count=inputs.public_a6_executable_count,
        public_a6_threshold=inputs.public_a6_threshold,
        public_b1_template_pair_count=inputs.public_b1_template_pair_count,
        public_b1_market_sample_size=inputs.public_b1_market_sample_size,
    )


def evaluate_structural_lane_readiness(inputs: StructuralLaneReadinessInputs) -> StructuralLaneReadiness:
    lane = str(inputs.lane).strip().lower()
    blocked_reasons: list[str] = []
    settlement_count = max(0, int(inputs.settlement_evidence_count))

    if lane == "a6":
        if inputs.maker_fill_proxy_rate is None or inputs.maker_fill_wilson_lower is None:
            blocked_reasons.append("maker_fill_proxy_unmeasured")
        elif float(inputs.maker_fill_wilson_lower) <= float(inputs.minimum_fill_wilson_lower):
            blocked_reasons.append("maker_fill_proxy_below_confidence_floor")

        if inputs.violation_half_life_seconds is None:
            blocked_reasons.append("violation_half_life_unmeasured")
        elif float(inputs.violation_half_life_seconds) < float(inputs.minimum_violation_half_life_seconds):
            blocked_reasons.append("violation_half_life_below_minimum")

        if inputs.public_a6_executable_count is not None and int(inputs.public_a6_executable_count) <= 0:
            threshold = f"{float(inputs.public_a6_threshold):.2f}"
            blocked_reasons.append(f"public_audit_zero_executable_constructions_below_{threshold}_gate")

        return _finalize_lane_status(
            inputs,
            blocked_reasons,
            shadow_ready=not blocked_reasons,
            micro_live_ready=not blocked_reasons and settlement_count >= int(inputs.minimum_settlement_evidence_count),
        )

    if lane == "b1":
        if inputs.classification_accuracy is None:
            blocked_reasons.append("classification_accuracy_unmeasured")
        elif float(inputs.classification_accuracy) < float(inputs.minimum_classification_accuracy):
            blocked_reasons.append("classification_accuracy_below_85pct")

        if inputs.false_positive_rate is None:
            blocked_reasons.append("false_positive_rate_unmeasured")
        elif float(inputs.false_positive_rate) > float(inputs.maximum_false_positive_rate):
            blocked_reasons.append("false_positive_rate_above_5pct")

        if inputs.public_b1_template_pair_count is not None and int(inputs.public_b1_template_pair_count) <= 0:
            sample_size = max(0, int(inputs.public_b1_market_sample_size))
            blocked_reasons.append(
                f"public_audit_zero_deterministic_pairs_in_first_{sample_size}_allowed_markets"
            )

        micro_live_ready = (
            not blocked_reasons
            and settlement_count >= int(inputs.minimum_settlement_evidence_count)
            and inputs.violation_half_life_seconds is not None
            and float(inputs.violation_half_life_seconds) >= float(inputs.minimum_violation_half_life_seconds)
        )
        return _finalize_lane_status(
            inputs,
            blocked_reasons,
            shadow_ready=not blocked_reasons,
            micro_live_ready=micro_live_ready,
        )

    raise ValueError(f"Unsupported structural lane: {inputs.lane}")


def evaluate_execution_readiness(inputs: ExecutionReadinessInputs) -> ExecutionReadiness:
    reasons: list[str] = []

    if not inputs.feed_healthy:
        reasons.append("feed_unhealthy")
    if not inputs.tick_size_ok:
        reasons.append("tick_size_stale")
    if not inputs.quote_surface_ok:
        reasons.append("quote_surface_incomplete")
    if float(inputs.estimated_one_leg_loss_usd) > float(inputs.max_one_leg_loss_threshold_usd):
        reasons.append("one_leg_loss_exceeds_threshold")
    if in_polymarket_restart_window(inputs.now):
        reasons.append("restart_window_active")
    if inputs.neg_risk and not inputs.neg_risk_flag_configured:
        reasons.append("neg_risk_flag_missing")
    if inputs.builder_required and not inputs.builder_available:
        reasons.append("builder_relayer_unavailable")

    status = "ready" if not reasons else "blocked"
    return ExecutionReadiness(
        ready=not reasons,
        status=status,
        reasons=tuple(reasons),
        estimated_one_leg_loss_usd=float(inputs.estimated_one_leg_loss_usd),
    )


def _load_json_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_service_status(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "unknown"

    running_tokens = {"running", "active"}
    stopped_tokens = {"stopped", "inactive", "failed"}
    values = {
        str(payload.get(key, "")).strip().lower()
        for key in ("status", "systemctl_state", "detail")
        if payload.get(key) not in (None, "")
    }
    if not values:
        return "unknown"

    has_running = any(value in running_tokens for value in values)
    has_stopped = any(value in stopped_tokens for value in values)

    if has_running and has_stopped:
        return "ambiguous"
    if has_running:
        return "running"
    if has_stopped:
        return "stopped"
    return "unknown"


def _extract_service_mode(*payloads: dict[str, Any] | None) -> str | None:
    mode_keys = ("mode", "service_mode", "runtime_mode", "jj_live_mode")
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in mode_keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip().lower()
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_fast_flow_restart_inputs(repo_root: str | Path) -> FastFlowRestartInputs:
    root = Path(repo_root).expanduser().resolve()
    artifact_paths = {
        "remote_cycle_status": root / "reports" / "remote_cycle_status.json",
        "remote_service_status": root / "reports" / "remote_service_status.json",
        "jj_state": root / "jj_state.json",
        "root_test_status": root / "reports" / "root_test_status.json",
    }
    required_artifacts = tuple(
        RestartRequiredArtifact(name=name, path=str(path), exists=path.exists())
        for name, path in artifact_paths.items()
    )
    return FastFlowRestartInputs(
        remote_cycle_status=_load_json_payload(artifact_paths["remote_cycle_status"]),
        remote_service_status=_load_json_payload(artifact_paths["remote_service_status"]),
        jj_state=_load_json_payload(artifact_paths["jj_state"]),
        root_test_status=_load_json_payload(artifact_paths["root_test_status"]),
        required_artifacts=required_artifacts,
    )


def evaluate_fast_flow_restart(inputs: FastFlowRestartInputs) -> FastFlowRestartDecision:
    cycle_status = inputs.remote_cycle_status if isinstance(inputs.remote_cycle_status, dict) else {}
    launch = cycle_status.get("launch", {}) if isinstance(cycle_status.get("launch"), dict) else {}
    wallet_flow = cycle_status.get("wallet_flow", {}) if isinstance(cycle_status.get("wallet_flow"), dict) else {}
    runtime = cycle_status.get("runtime", {}) if isinstance(cycle_status.get("runtime"), dict) else {}
    cycle_service = cycle_status.get("service", {}) if isinstance(cycle_status.get("service"), dict) else {}
    cycle_root_tests = cycle_status.get("root_tests", {}) if isinstance(cycle_status.get("root_tests"), dict) else {}
    root_test_status = inputs.root_test_status if isinstance(inputs.root_test_status, dict) else cycle_root_tests

    blocked_reasons: list[str] = []

    for artifact in inputs.required_artifacts:
        if not artifact.exists:
            blocked_reasons.append(f"required_artifact_missing:{artifact.name}")

    root_status = str(root_test_status.get("status") or cycle_root_tests.get("status") or "unknown").strip().lower()
    if root_status != "passing":
        blocked_reasons.append("root_tests_not_passing")

    cycle_root_status = str(cycle_root_tests.get("status") or "").strip().lower()
    if cycle_root_status and root_status != "unknown" and cycle_root_status != root_status:
        blocked_reasons.append("root_test_status_drift")

    wallet_ready = bool(wallet_flow.get("ready"))
    wallet_status = str(wallet_flow.get("status") or "").strip().lower()
    if not wallet_ready or wallet_status == "not_ready":
        blocked_reasons.append("wallet_bootstrap_not_ready")
        for reason in wallet_flow.get("reasons") or ():
            blocked_reasons.append(f"wallet_bootstrap_reason:{reason}")

    standalone_service_status = _normalize_service_status(inputs.remote_service_status)
    cycle_service_status = _normalize_service_status(cycle_service)
    effective_service_status = (
        standalone_service_status
        if standalone_service_status != "unknown"
        else cycle_service_status
    )

    service_mode = _extract_service_mode(inputs.remote_service_status, cycle_service, runtime, launch)
    if (
        standalone_service_status not in {"unknown", cycle_service_status}
        and cycle_service_status != "unknown"
    ):
        blocked_reasons.append("remote_service_state_ambiguous")
        blocked_reasons.append("remote_service_artifacts_disagree")
    if effective_service_status in {"unknown", "ambiguous"}:
        blocked_reasons.append("remote_service_state_ambiguous")
    elif effective_service_status == "running":
        if not service_mode:
            blocked_reasons.append("remote_service_state_ambiguous")
            blocked_reasons.append("remote_service_mode_unconfirmed")
        if bool(launch.get("live_launch_blocked")):
            blocked_reasons.append("remote_service_state_ambiguous")
            blocked_reasons.append("remote_service_running_while_launch_blocked")

    cycle_count = _safe_int(runtime.get("cycles_completed"), default=-1)
    jj_cycle_count = _safe_int(
        (inputs.jj_state or {}).get("cycles_completed") if isinstance(inputs.jj_state, dict) else None,
        default=-1,
    )
    if cycle_count >= 0 and jj_cycle_count >= 0 and cycle_count != jj_cycle_count:
        blocked_reasons.append("cycles_completed_drift")

    reasons = tuple(dict.fromkeys(blocked_reasons))
    restart_ready = not reasons
    recommended_mode = RECOMMENDED_MODE_HOLD
    if restart_ready:
        closed_trades = _safe_int(runtime.get("closed_trades"), default=0)
        recommended_mode = (
            RECOMMENDED_MODE_SHADOW if closed_trades > 0 else RECOMMENDED_MODE_PAPER
        )

    return FastFlowRestartDecision(
        restart_ready=restart_ready,
        blocked_reasons=reasons,
        required_artifacts=tuple(inputs.required_artifacts),
        recommended_mode=recommended_mode,
        service_status=effective_service_status,
        cycles_completed=max(cycle_count, jj_cycle_count, 0),
        root_tests_status=root_status,
        wallet_ready=wallet_ready,
    )


def build_fast_flow_restart_report(repo_root: str | Path) -> dict[str, Any]:
    inputs = load_fast_flow_restart_inputs(repo_root)
    decision = evaluate_fast_flow_restart(inputs)
    cycle_status = inputs.remote_cycle_status if isinstance(inputs.remote_cycle_status, dict) else {}
    runtime = cycle_status.get("runtime", {}) if isinstance(cycle_status.get("runtime"), dict) else {}
    launch = cycle_status.get("launch", {}) if isinstance(cycle_status.get("launch"), dict) else {}
    wallet_flow = cycle_status.get("wallet_flow", {}) if isinstance(cycle_status.get("wallet_flow"), dict) else {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "restart_ready": decision.restart_ready,
        "blocked_reasons": list(decision.blocked_reasons),
        "required_artifacts": [asdict(artifact) for artifact in decision.required_artifacts],
        "recommended_mode": decision.recommended_mode,
        "service_status": decision.service_status,
        "cycles_completed": decision.cycles_completed,
        "wallet_ready": decision.wallet_ready,
        "wallet_count": _safe_int(wallet_flow.get("wallet_count"), default=0),
        "root_tests_status": decision.root_tests_status,
        "closed_trades": _safe_int(runtime.get("closed_trades"), default=0),
        "live_launch_blocked": bool(launch.get("live_launch_blocked")),
    }


def write_fast_flow_restart_report(
    repo_root: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(repo_root).expanduser().resolve()
    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = root / "reports" / f"restart_gate_{timestamp}.json"
    else:
        output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_fast_flow_restart_report(root), indent=2, sort_keys=True))
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the fast-flow restart gate from repo runtime artifacts."
    )
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parents[1],
        help="Repo root containing jj_state.json and reports/*.json",
    )
    parser.add_argument(
        "--output",
        help="Optional explicit JSON output path. Defaults to reports/restart_gate_<timestamp>.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = write_fast_flow_restart_report(args.repo_root, output_path=args.output)
    print(output)


if __name__ == "__main__":
    main()
