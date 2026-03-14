#!/usr/bin/env python3
"""Instance 6 rollout-control, finance-gating, and rollback dispatch packet."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

LADDER = (
    "shadow_replay",
    "shadow_live_intents",
    "single_follower_5usd_micro_live",
    "two_asset_basket",
    "four_asset_basket",
)
FOLLOWER_ASSETS = ("ETH", "SOL", "XRP", "DOGE")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        token = str(item).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _first_time(payload: dict[str, Any], path: Path) -> datetime:
    for key in (
        "generated_at",
        "checked_at",
        "timestamp",
        "report_generated_at",
        "updated_at",
    ):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _artifact_health(*, root: Path, rel_path: str, now: datetime, max_age_seconds: int) -> dict[str, Any]:
    path = root / rel_path
    if not path.exists():
        return {
            "path": rel_path,
            "exists": False,
            "fresh": False,
            "generated_at": None,
            "age_seconds": None,
            "reason": f"missing:{rel_path}",
            "payload": {},
        }
    payload = _read_json(path)
    generated_at = _first_time(payload, path)
    age_seconds = max(0.0, (now - generated_at).total_seconds())
    fresh = age_seconds <= float(max_age_seconds)
    return {
        "path": rel_path,
        "exists": True,
        "fresh": fresh,
        "generated_at": generated_at.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "reason": None if fresh else f"stale:{rel_path}:{int(round(age_seconds))}s>{max_age_seconds}s",
        "payload": payload,
    }


def _extract_stage(value: Any) -> int:
    if isinstance(value, int):
        return max(0, value)
    text = str(value or "").strip().lower()
    if not text:
        return 0
    match = re.search(r"stage[_\s-]*(\d+)", text)
    if match:
        return max(0, _as_int(match.group(1), 0))
    return max(0, _as_int(value, 0))


def _extract_registry_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("registry", "rows", "markets", "items", "records", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _extract_registry_asset(row: dict[str, Any]) -> str:
    for key in ("asset", "symbol", "base_asset", "underlier", "underlying_asset"):
        value = str(row.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _extract_quote_staleness(row: dict[str, Any]) -> float | None:
    for key in (
        "staleness_seconds",
        "quote_staleness_seconds",
        "mid_staleness_seconds",
        "best_quote_staleness_seconds",
        "book_staleness_seconds",
    ):
        if key in row:
            return _as_float(row.get(key), 0.0)
    return None


def _extract_max_quote_staleness(payload: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    row_values = [value for value in (_extract_quote_staleness(row) for row in rows) if value is not None]
    if row_values:
        return max(row_values)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ("max_quote_staleness_seconds", "max_staleness_seconds", "quote_staleness_seconds"):
            if key in summary:
                return _as_float(summary.get(key), 0.0)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        for key in ("max_quote_staleness_seconds", "max_staleness_seconds", "quote_staleness_seconds"):
            if key in metrics:
                return _as_float(metrics.get(key), 0.0)
    return 0.0


def _extract_bool_flag(payload: dict[str, Any], *paths: tuple[str, ...]) -> bool:
    for path in paths:
        node: Any = payload
        found = True
        for key in path:
            if not isinstance(node, dict) or key not in node:
                found = False
                break
            node = node[key]
        if found and bool(node):
            return True
    return False


def _extract_value(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        node: Any = payload
        found = True
        for key in path:
            if not isinstance(node, dict) or key not in node:
                found = False
                break
            node = node[key]
        if found:
            return node
    return None


def _next_retry(now: datetime, minutes: int) -> str:
    return (now + timedelta(minutes=int(minutes))).isoformat()


def _build_ladder(active_index: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, name in enumerate(LADDER):
        if idx < active_index:
            status = "completed"
        elif idx == active_index:
            status = "active"
        else:
            status = "locked"
        rows.append({"index": idx, "name": name, "status": status})
    return rows


def build_instance6_dispatch(root: Path) -> dict[str, Any]:
    now = _utc_now()
    reports = root / "reports"
    runtime_truth = _read_json(reports / "runtime_truth_latest.json")
    state_improvement = _read_json(reports / "state_improvement_latest.json")
    finance_latest = _read_json(reports / "finance" / "latest.json")
    model_budget_plan = _read_json(reports / "finance" / "model_budget_plan.json")
    action_queue = _read_json(reports / "finance" / "action_queue.json")
    previous_rollout = _read_json(reports / "rollout_control" / "latest.json")
    instance2_baseline = _read_json(reports / "instance2_btc5_baseline" / "latest.json")

    critical_artifacts = {
        "data_plane_health": _artifact_health(
            root=root,
            rel_path="reports/data_plane_health/latest.json",
            now=now,
            max_age_seconds=60,
        ),
        "market_registry": _artifact_health(
            root=root,
            rel_path="reports/market_registry/latest.json",
            now=now,
            max_age_seconds=60,
        ),
        "cross_asset_cascade": _artifact_health(
            root=root,
            rel_path="reports/cross_asset_cascade/latest.json",
            now=now,
            max_age_seconds=60,
        ),
        "cross_asset_mc": _artifact_health(
            root=root,
            rel_path="reports/cross_asset_mc/latest.json",
            now=now,
            max_age_seconds=60,
        ),
    }

    stale_or_missing = [
        artifact["reason"]
        for artifact in critical_artifacts.values()
        if not artifact["fresh"] and artifact.get("reason")
    ]

    registry_payload = critical_artifacts["market_registry"]["payload"]
    registry_rows = _extract_registry_rows(registry_payload)
    follower_assets_seen = {
        asset
        for asset in (_extract_registry_asset(row) for row in registry_rows)
        if asset in FOLLOWER_ASSETS
    }
    follower_mapping_complete = all(asset in follower_assets_seen for asset in FOLLOWER_ASSETS)
    max_quote_staleness_seconds = _extract_max_quote_staleness(registry_payload, registry_rows)
    quote_stale = max_quote_staleness_seconds > 60.0

    data_plane_payload = critical_artifacts["data_plane_health"]["payload"]
    sequence_gap_count = _as_int(
        _extract_value(
            data_plane_payload,
            ("sequence_gap_count",),
            ("metrics", "sequence_gap_count"),
            ("metrics", "total_sequence_gaps"),
            ("health", "sequence_gap_count"),
        ),
        0,
    )
    book_stale_breach_count = _as_int(
        _extract_value(
            data_plane_payload,
            ("book_staleness_breach_count",),
            ("metrics", "book_staleness_breach_count"),
            ("metrics", "book_staleness_breaches"),
        ),
        0,
    )
    feed_disagreement_count = _as_int(
        _extract_value(
            data_plane_payload,
            ("feed_disagreement_count",),
            ("metrics", "feed_disagreement_count"),
            ("metrics", "leader_follower_feed_disagreement_count"),
        ),
        0,
    )

    mc_payload = critical_artifacts["cross_asset_mc"]["payload"]
    mc_tail_breach = _extract_bool_flag(
        mc_payload,
        ("tail_risk_breach",),
        ("risk_flags", "tail_risk_breach"),
        ("stress", "tail_risk_breach"),
    )
    mc_drawdown_breach = _extract_bool_flag(
        mc_payload,
        ("drawdown_stress_breach",),
        ("risk_flags", "drawdown_stress_breach"),
        ("stress", "drawdown_stress_breach"),
    )
    mc_correlation_collapse = _extract_bool_flag(
        mc_payload,
        ("correlation_collapse",),
        ("risk_flags", "correlation_collapse"),
        ("stress", "correlation_collapse"),
    )

    runtime_summary = runtime_truth.get("summary") if isinstance(runtime_truth.get("summary"), dict) else {}
    deployment_confidence = (
        runtime_truth.get("deployment_confidence")
        if isinstance(runtime_truth.get("deployment_confidence"), dict)
        else {}
    )
    stage_label = (
        runtime_summary.get("btc5_allowed_stage")
        or runtime_truth.get("btc5_allowed_stage")
        or (runtime_truth.get("btc5_stage_readiness") or {}).get("allowed_stage_label")
    )
    stage_value = _extract_stage(stage_label)
    allow_order_submission = bool(runtime_truth.get("allow_order_submission"))
    launch_posture = str(
        runtime_summary.get("launch_posture")
        or (runtime_truth.get("launch") or {}).get("posture")
        or ""
    ).strip().lower()
    baseline_contract = (
        instance2_baseline.get("baseline_contract")
        if isinstance(instance2_baseline.get("baseline_contract"), dict)
        else {}
    )
    baseline_guard_contract = (
        instance2_baseline.get("baseline_guard")
        if isinstance(instance2_baseline.get("baseline_guard"), dict)
        else {}
    )
    btc5_status = str((runtime_truth.get("btc_5min_maker") or {}).get("status") or "").strip().lower()
    btc5_rows = _as_int((runtime_truth.get("btc_5min_maker") or {}).get("live_filled_rows"), 0)
    baseline_status = str(baseline_contract.get("baseline_status") or "").strip().lower()
    btc5_baseline_ready = bool(
        baseline_contract.get("baseline_live_ok")
        if baseline_contract
        else (btc5_status in {"ok", "healthy"} and btc5_rows > 0)
    )

    active_thresholds = (
        state_improvement.get("active_thresholds")
        if isinstance(state_improvement.get("active_thresholds"), dict)
        else {}
    )
    max_position_usd = _as_float(active_thresholds.get("max_position_usd"), 0.0)
    executed_notional_hourly = _as_float(
        _extract_value(
            state_improvement,
            ("per_venue_executed_notional_usd", "combined_hourly"),
            ("metrics", "executed_notional_usd"),
        ),
        0.0,
    )
    candidate_conversion = _as_float(
        _extract_value(
            state_improvement,
            ("metrics", "candidate_to_trade_conversion"),
            ("candidate_to_trade_conversion",),
        ),
        0.0,
    )

    finance_gate_pass = bool(
        finance_latest.get("finance_gate_pass")
        if finance_latest.get("finance_gate_pass") is not None
        else ((finance_latest.get("finance_gate") or {}).get("pass"))
    )
    finance_gate_reason = str(
        ((finance_latest.get("finance_gate") or {}).get("reason"))
        or "unknown"
    ).strip()
    finance_gate_status = str(
        ((finance_latest.get("finance_gate") or {}).get("status"))
        or ("pass" if finance_gate_pass else "hold")
    ).strip().lower()
    model_budget_required = (
        model_budget_plan.get("required_outputs")
        if isinstance(model_budget_plan.get("required_outputs"), dict)
        else {}
    )
    model_budget_queue_package = (
        model_budget_plan.get("queue_package")
        if isinstance(model_budget_plan.get("queue_package"), dict)
        else {}
    )
    model_budget_operating_points = (
        model_budget_plan.get("operating_points")
        if isinstance(model_budget_plan.get("operating_points"), list)
        else []
    )

    single_action_cap_usd = _as_float(os.getenv("JJ_FINANCE_SINGLE_ACTION_CAP_USD"), 250.0)
    monthly_commitment_cap_usd = _as_float(os.getenv("JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD"), 1000.0)
    queued_actions = [
        action
        for action in (action_queue.get("actions") if isinstance(action_queue.get("actions"), list) else [])
        if isinstance(action, dict)
    ]
    active_actions = [
        action
        for action in queued_actions
        if str(action.get("status") or "").strip().lower() in {"queued", "executed", "shadowed", "approved"}
    ]
    single_cap_violations = [
        str(action.get("action_key") or "unknown")
        for action in active_actions
        if _as_float(action.get("amount_usd"), 0.0) > single_action_cap_usd
    ]
    monthly_commitment_total = sum(
        _as_float(action.get("monthly_commitment_usd"), 0.0)
        for action in active_actions
    )
    monthly_cap_pass = monthly_commitment_total <= monthly_commitment_cap_usd

    finance_policy_blockers: list[str] = []
    if single_cap_violations:
        finance_policy_blockers.append(
            f"single_action_cap_exceeded:{','.join(single_cap_violations)}"
        )
    if not monthly_cap_pass:
        finance_policy_blockers.append(
            f"monthly_commitment_cap_exceeded:{monthly_commitment_total:.2f}>{monthly_commitment_cap_usd:.2f}"
        )

    finance_gate_effective_pass = finance_gate_pass and not finance_policy_blockers
    finance_block_reasons: list[str] = []
    if not finance_gate_pass:
        finance_block_reasons.append(f"finance_gate_blocked:{finance_gate_reason or 'unknown'}")
    finance_block_reasons.extend(finance_policy_blockers)

    selected_action = None
    queued_for_execution = [
        action
        for action in queued_actions
        if str(action.get("status") or "").strip().lower() == "queued"
    ]
    if queued_for_execution:
        queued_for_execution.sort(
            key=lambda action: _as_float(action.get("priority_score"), 0.0),
            reverse=True,
        )
        top = queued_for_execution[0]
        selected_action = {
            "action_key": top.get("action_key"),
            "amount_usd": _as_float(top.get("amount_usd"), 0.0),
            "destination": top.get("destination"),
            "status": "ready_to_execute" if finance_gate_effective_pass else "blocked_by_policy",
            "reason": top.get("reason"),
        }
    elif isinstance(finance_latest.get("one_next_cycle_action"), dict):
        next_action = finance_latest.get("one_next_cycle_action") or {}
        selected_action = {
            "action_key": next_action.get("action_key"),
            "amount_usd": _as_float(next_action.get("amount_usd"), 0.0),
            "destination": next_action.get("destination"),
            "status": str(next_action.get("status") or "queued"),
            "reason": next_action.get("reason"),
        }

    follower_count_ready = len(follower_assets_seen)
    stale_branch_active = bool(stale_or_missing)
    mapping_blockers: list[str] = []
    if not follower_mapping_complete:
        mapping_blockers.append("market_registry_mapping_incomplete")
    if quote_stale:
        mapping_blockers.append(f"market_registry_quote_staleness_gt_60s:{max_quote_staleness_seconds:.2f}")
    feed_blockers: list[str] = []
    if sequence_gap_count > 0:
        feed_blockers.append(f"sequence_gap_count_gt_zero:{sequence_gap_count}")
    if book_stale_breach_count > 0:
        feed_blockers.append(f"book_staleness_breach_count_gt_zero:{book_stale_breach_count}")
    if feed_disagreement_count > 0:
        feed_blockers.append(f"leader_follower_feed_disagreement_count_gt_zero:{feed_disagreement_count}")

    risk_breach_reasons: list[str] = []
    if mc_tail_breach:
        risk_breach_reasons.append("mc_tail_risk_breach")
    if mc_drawdown_breach:
        risk_breach_reasons.append("mc_drawdown_stress_breach")
    if mc_correlation_collapse:
        risk_breach_reasons.append("mc_correlation_collapse")

    policy_blockers: list[str] = []
    if max_position_usd > 5.0:
        policy_blockers.append(f"micro_live_position_cap_exceeded:{max_position_usd:.2f}>5.00")

    block_reasons = _dedupe(
        stale_or_missing
        + mapping_blockers
        + feed_blockers
        + risk_breach_reasons
        + finance_block_reasons
        + policy_blockers
    )

    current_stage_index = _as_int(previous_rollout.get("rollout_ladder", {}).get("active_stage_index"), 0)
    current_stage_index = min(max(0, current_stage_index), len(LADDER) - 1)

    desired_stage_index = 0
    if not stale_branch_active and not mapping_blockers and not feed_blockers:
        desired_stage_index = 1
    if (
        desired_stage_index >= 1
        and finance_gate_effective_pass
        and allow_order_submission
        and stage_value >= 1
        and not policy_blockers
    ):
        desired_stage_index = 2
    if desired_stage_index >= 2 and candidate_conversion > 0.0 and follower_count_ready >= 2:
        desired_stage_index = 3
    if desired_stage_index >= 2 and candidate_conversion > 0.0 and follower_count_ready >= 4:
        desired_stage_index = 4

    if risk_breach_reasons:
        operator_decision = "rollback"
        desired_stage_index = 0
        decision_reason = "risk_or_correlation_threshold_breach_requires_baseline_revert"
        retry_in_minutes = 5
    elif block_reasons:
        operator_decision = "block"
        desired_stage_index = 0 if stale_branch_active else min(desired_stage_index, 1)
        decision_reason = "hold_repair_until_blockers_clear"
        retry_in_minutes = 5 if stale_branch_active else 10
    else:
        operator_decision = "action"
        decision_reason = "rollout_gates_green"
        retry_in_minutes = 5

    next_action_text: str
    if operator_decision == "rollback":
        next_action_text = (
            "Rollback cascade sizing to zero for affected followers and run BTC5 baseline only; "
            "recheck risk metrics in 5 minutes."
        )
    elif operator_decision == "block":
        if stale_branch_active:
            next_action_text = (
                "Hold cascade execution and keep collectors running; repair stale/missing cross-asset artifacts and retry in 5 minutes."
            )
        elif finance_block_reasons:
            next_action_text = (
                "Hold live rollout progression until finance policy blockers clear; keep shadow replay and retry after finance gate remediation."
            )
        else:
            next_action_text = (
                "Hold rollout at shadow intents, repair blocker set, and retry after the next control-plane cycle."
            )
    elif desired_stage_index > current_stage_index:
        next_action_text = (
            f"Advance rollout from `{LADDER[current_stage_index]}` to `{LADDER[desired_stage_index]}` and keep BTC5 baseline guardrails active."
        )
    else:
        next_action_text = (
            f"Maintain `{LADDER[desired_stage_index]}` and continue continuous monitoring with finance/risk gates enforced."
        )

    retry_at = _next_retry(now, retry_in_minutes)
    cascade_enabled = operator_decision == "action" and desired_stage_index >= 2
    cascade_guard_mode = (
        "enabled"
        if cascade_enabled
        else "disabled_collectors_only"
    )

    arr_confidence_score = _as_float(
        _extract_value(
            runtime_truth,
            ("deployment_confidence", "overall_score"),
            ("summary", "arr_confidence_score"),
        ),
        0.0,
    )
    candidate_delta_arr_bps = int(
        round(
            _as_float(
                _extract_value(
                    runtime_truth,
                    ("btc5_selected_package", "median_arr_delta_pct"),
                    ("state_improvement", "strategy_recommendations", "public_performance_scoreboard", "raw_selected_forecast_arr_pct"),
                ),
                0.0,
            )
            * 100.0
        )
    )
    expected_velocity_delta = _as_float(
        _extract_value(
            state_improvement,
            ("improvement_velocity", "deltas", "candidate_to_trade_conversion_delta"),
            ("improvement_velocity", "deltas", "edge_reachability_delta"),
        ),
        0.0,
    )

    required_outputs = {
        "candidate_delta_arr_bps": candidate_delta_arr_bps,
        "expected_improvement_velocity_delta": expected_velocity_delta,
        "arr_confidence_score": round(arr_confidence_score, 4),
        "block_reasons": block_reasons,
        "finance_gate_pass": finance_gate_effective_pass,
        "one_next_cycle_action": next_action_text,
    }

    payload = {
        "instance": 6,
        "instance_label": "rollout_control_finance_rollback",
        "generated_at": now.isoformat(),
        "objective": (
            "Control aggressive cross-asset rollout with staged ladders, stale-input hold/repair retries, "
            "finance cap enforcement, and explicit rollback paths while preserving BTC5 baseline."
        ),
        "sources": {
            "runtime_truth_latest": "reports/runtime_truth_latest.json",
            "state_improvement_latest": "reports/state_improvement_latest.json",
            "finance_latest": "reports/finance/latest.json",
            "finance_model_budget": "reports/finance/model_budget_plan.json",
            "finance_action_queue": "reports/finance/action_queue.json",
            "data_plane_health": "reports/data_plane_health/latest.json",
            "market_registry": "reports/market_registry/latest.json",
            "cross_asset_cascade": "reports/cross_asset_cascade/latest.json",
            "cross_asset_mc": "reports/cross_asset_mc/latest.json",
        },
        "baseline_guard": {
            "btc5_baseline_ready": btc5_baseline_ready,
            "baseline_status": baseline_status or "unknown",
            "btc5_status": btc5_status or "unknown",
            "btc5_live_filled_rows": btc5_rows,
            "launch_posture": launch_posture or "unknown",
            "allow_order_submission": allow_order_submission,
            "allowed_stage_label": stage_label or "unknown",
            "allowed_stage": stage_value,
            "status_triplet": baseline_guard_contract.get("status_triplet"),
            "permitted_baseline_attempts": baseline_guard_contract.get("permitted_baseline_attempts"),
            "blocked_actions": baseline_guard_contract.get("blocked_actions"),
            "hold_repair": baseline_guard_contract.get("hold_repair"),
            "control_modes": baseline_guard_contract.get("control_modes"),
            "source_path": "reports/instance2_btc5_baseline/latest.json",
        },
        "cross_asset_health": {
            "artifacts": {
                key: {k: v for k, v in value.items() if k != "payload"}
                for key, value in critical_artifacts.items()
            },
            "follower_assets_required": list(FOLLOWER_ASSETS),
            "follower_assets_seen": sorted(follower_assets_seen),
            "follower_mapping_complete": follower_mapping_complete,
            "max_quote_staleness_seconds": round(max_quote_staleness_seconds, 3),
            "sequence_gap_count": sequence_gap_count,
            "book_staleness_breach_count": book_stale_breach_count,
            "leader_follower_feed_disagreement_count": feed_disagreement_count,
        },
        "rollout_ladder": {
            "policy": "shadow_replay -> shadow_live_intents -> single_follower_5usd_micro_live -> two_asset_basket -> four_asset_basket",
            "current_stage_index": current_stage_index,
            "current_stage_name": LADDER[current_stage_index],
            "active_stage_index": desired_stage_index,
            "active_stage_name": LADDER[desired_stage_index],
            "stages": _build_ladder(desired_stage_index),
            "candidate_to_trade_conversion": candidate_conversion,
            "executed_notional_hourly_usd": executed_notional_hourly,
            "follower_count_ready": follower_count_ready,
        },
        "stale_hold_repair": {
            "active": stale_branch_active,
            "retry_in_minutes": 5 if stale_branch_active else None,
            "retry_at": _next_retry(now, 5) if stale_branch_active else None,
            "named_blockers": stale_or_missing,
        },
        "cascade_execution_guard": {
            "enabled": cascade_enabled,
            "mode": cascade_guard_mode,
            "reasons": _dedupe(stale_or_missing + mapping_blockers + feed_blockers + risk_breach_reasons),
        },
        "finance_gate": {
            "status": finance_gate_status,
            "reason": finance_gate_reason or "unknown",
            "finance_gate_pass": finance_gate_pass,
            "finance_gate_effective_pass": finance_gate_effective_pass,
            "single_action_cap_usd": single_action_cap_usd,
            "monthly_new_commitment_cap_usd": monthly_commitment_cap_usd,
            "single_action_cap_violations": single_cap_violations,
            "monthly_commitment_total_usd": round(monthly_commitment_total, 3),
            "monthly_commitment_cap_pass": monthly_cap_pass,
            "selected_action": selected_action,
            "policy_blockers": finance_policy_blockers,
        },
        "research_tooling_budget": {
            "artifact_present": bool(model_budget_plan),
            "generated_at": model_budget_plan.get("generated_at"),
            "queue_package_status": model_budget_queue_package.get("status"),
            "queue_package_operating_point": model_budget_queue_package.get("operating_point"),
            "queue_package_monthly_total_usd": model_budget_queue_package.get("monthly_total_usd"),
            "queue_package_policy_compliant": model_budget_queue_package.get("policy_compliant"),
            "required_block_reasons": model_budget_required.get("block_reasons") or [],
            "one_next_cycle_action": model_budget_required.get("one_next_cycle_action"),
            "operating_points": [
                {
                    "operating_point": item.get("operating_point"),
                    "monthly_budget_usd": item.get("monthly_budget_usd"),
                    "recommended_now": item.get("recommended_now"),
                }
                for item in model_budget_operating_points
                if isinstance(item, dict)
            ],
        },
        "operator_packet": {
            "decision": operator_decision,
            "decision_reason": decision_reason,
            "action": (
                "rollback_to_btc5_baseline_only"
                if operator_decision == "rollback"
                else (
                    f"advance_to_{LADDER[desired_stage_index]}"
                    if operator_decision == "action"
                    else "hold_repair"
                )
            ),
            "retry_in_minutes": retry_in_minutes,
            "retry_at": retry_at,
            "blockers": block_reasons,
            "next_action": next_action_text,
        },
        "required_outputs": required_outputs,
        "candidate_delta_arr_bps": required_outputs["candidate_delta_arr_bps"],
        "expected_improvement_velocity_delta": required_outputs["expected_improvement_velocity_delta"],
        "arr_confidence_score": required_outputs["arr_confidence_score"],
        "block_reasons": required_outputs["block_reasons"],
        "finance_gate_pass": required_outputs["finance_gate_pass"],
        "one_next_cycle_action": required_outputs["one_next_cycle_action"],
    }
    return payload


def write_instance6_dispatch(root: Path) -> tuple[Path, Path]:
    payload = build_instance6_dispatch(root)
    stamp = _utc_stamp(_parse_datetime(payload.get("generated_at")) or _utc_now())
    parallel_dir = root / "reports" / "parallel"
    rollout_dir = root / "reports" / "rollout_control"

    timestamped_path = parallel_dir / f"instance06_rollout_finance_dispatch_{stamp}.json"
    latest_parallel = parallel_dir / "instance06_rollout_finance_dispatch.json"
    latest_rollout = rollout_dir / "latest.json"

    _write_json(timestamped_path, payload)
    _write_json(latest_parallel, payload)
    _write_json(latest_rollout, payload)
    return timestamped_path, latest_rollout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Instance 6 rollout/finance/rollback dispatch artifact.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Workspace root (default: current directory).",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    packet_path, rollout_path = write_instance6_dispatch(root)
    print(
        json.dumps(
            {
                "instance6_packet": str(packet_path),
                "rollout_control_latest": str(rollout_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
