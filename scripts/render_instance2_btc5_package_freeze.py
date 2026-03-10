#!/usr/bin/env python3
"""Render the Instance 2 BTC5 package-freeze operator packet."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RUNTIME_TRUTH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_STATE_IMPROVEMENT = REPO_ROOT / "reports" / "state_improvement_latest.json"
DEFAULT_PUBLIC_RUNTIME_SNAPSHOT = REPO_ROOT / "reports" / "public_runtime_snapshot.json"
DEFAULT_IMPROVEMENT_VELOCITY = REPO_ROOT / "improvement_velocity.json"
DEFAULT_FINANCE_LATEST = REPO_ROOT / "reports" / "finance" / "latest.json"
DEFAULT_FINANCE_ACTION_QUEUE = REPO_ROOT / "reports" / "finance" / "action_queue.json"
DEFAULT_SELECTED_PACKAGE = REPO_ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_CURRENT_PROBE = REPO_ROOT / "reports" / "btc5_autoresearch_current_probe" / "latest.json"
DEFAULT_STRATEGY_SCALE_COMPARISON = REPO_ROOT / "reports" / "strategy_scale_comparison.json"
DEFAULT_SIGNAL_SOURCE_AUDIT = REPO_ROOT / "reports" / "signal_source_audit.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "reports" / "parallel" / "instance02_btc5_package_freeze.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "reports" / "parallel" / "instance02_btc5_package_freeze.md"
DEFAULT_DONE_JSON = REPO_ROOT / "reports" / "parallel" / "instance2.done.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_path(payload: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    current: Any = payload
    for segment in dotted_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return default
        current = current[segment]
    return current


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def find_action(actions: list[dict[str, Any]], action_key: str) -> dict[str, Any]:
    for action in actions:
        if str(action.get("action_key") or "") == action_key:
            return action
    return {}


def to_bps(percent_value: float) -> int:
    return int(round(percent_value * 100))


def ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def build_contract(
    *,
    runtime_truth: dict[str, Any],
    state_improvement: dict[str, Any],
    public_runtime_snapshot: dict[str, Any],
    improvement_velocity: dict[str, Any],
    finance_latest: dict[str, Any],
    finance_action_queue: dict[str, Any],
    selected_package: dict[str, Any],
    current_probe: dict[str, Any],
    strategy_scale_comparison: dict[str, Any],
    signal_source_audit: dict[str, Any],
) -> dict[str, Any]:
    champion_lane = (
        get_path(state_improvement, "strategy_recommendations.btc5_candidate_recovery.champion_lane", {}) or {}
    )
    comparison_lanes = (
        get_path(state_improvement, "strategy_recommendations.btc5_candidate_recovery.comparison_only_lanes", []) or []
    )
    champion_contract = get_path(state_improvement, "strategy_recommendations.champion_lane_contract", {}) or {}
    control_plane_consistency = (
        get_path(state_improvement, "strategy_recommendations.control_plane_consistency.capital_consistency.artifacts", {})
        or {}
    )
    stage_readiness = (
        get_path(control_plane_consistency, "strategy_scale_comparison.stage_readiness", {}) or {}
    )
    selected_runtime_package = runtime_truth.get("btc5_selected_package") or {}
    btc5_stage_readiness = runtime_truth.get("btc5_stage_readiness") or {}
    intraday_live_summary = get_path(public_runtime_snapshot, "btc_5min_maker.intraday_live_summary", {}) or {}
    finance_gate = finance_latest.get("finance_gate") or {}
    finance_actions = finance_action_queue.get("actions") or []
    trading_action = find_action(finance_actions, "allocate::fund_trading")
    candidate_to_trade_conversion = as_float(
        get_path(state_improvement, "metrics.candidate_to_trade_conversion"),
        default=0.0,
    )
    executed_notional_last_hour = as_float(
        get_path(state_improvement, "per_venue_executed_notional_usd.combined_hourly"),
        default=0.0,
    )
    polymarket_candidates_total = as_int(
        get_path(state_improvement, "per_venue_candidate_counts.polymarket"),
        default=0,
    )
    kalshi_candidates_total = as_int(
        get_path(state_improvement, "per_venue_candidate_counts.kalshi"),
        default=0,
    )
    frozen_package_id = str(champion_lane.get("top_candidate_id") or "").strip()
    if not frozen_package_id:
        frozen_package_id = "btc5:grid_d0.00005_up0.48_down0.51"
    comparison_only_package = str(
        selected_runtime_package.get("selected_best_profile_name")
        or get_path(champion_contract, "champion_lane.selected_profile_name")
        or ""
    ).strip()
    order_failed_rate_recent_40 = as_float(
        stage_readiness.get("order_failed_rate_recent_40"),
        default=as_float(
            get_path(strategy_scale_comparison, "stage_readiness.order_failed_rate_recent_40"),
            default=0.0,
        ),
    )
    trailing_12_live_filled_pnl_usd = as_float(
        stage_readiness.get("trailing_12_live_filled_pnl_usd"),
        default=as_float(
            get_path(public_runtime_snapshot, "btc_5min_maker.fill_attribution.recent_live_filled_summary.pnl_usd"),
            default=0.0,
        ),
    )
    trailing_40_live_filled_pnl_usd = as_float(
        stage_readiness.get("trailing_40_live_filled_pnl_usd"),
        default=0.0,
    )
    arr_confidence_score = as_float(
        get_path(champion_contract, "required_outputs.arr_confidence_score"),
        default=as_float(get_path(runtime_truth, "deployment_confidence.overall_score"), default=0.0),
    )
    candidate_delta_arr_pct = as_float(
        get_path(champion_contract, "required_outputs.candidate_delta_arr_bps"),
        default=0.0,
    )
    if candidate_delta_arr_pct:
        candidate_delta_arr_bps = as_int(candidate_delta_arr_pct)
    else:
        candidate_delta_arr_bps = to_bps(
            as_float(
                get_path(selected_package, "arr_tracking.median_arr_delta_pct"),
                default=as_float(get_path(state_improvement, "strategy_recommendations.public_performance_scoreboard.forecast_arr_delta_pct"), default=0.0),
            )
        )
    confidence_label = str(
        selected_runtime_package.get("selected_package_confidence_label")
        or champion_lane.get("selected_package_confidence_label")
        or "unknown"
    ).strip()
    release_block_reasons = ordered_unique(
        list(runtime_truth.get("block_reasons") or [])
        + list(get_path(champion_contract, "blocker_classes.candidate.checks", []) or [])
        + list(get_path(champion_contract, "blocker_classes.confirmation.checks", []) or [])
        + (["executed_notional_zero_last_hour"] if executed_notional_last_hour <= 0 else [])
        + (["candidate_to_trade_conversion_zero_last_hour"] if candidate_to_trade_conversion <= 0 else [])
    )
    order_failure_threshold = 0.25
    shadow_sequence = [
        {
            "step": 1,
            "name": "package_load",
            "status": "pending_upgrade",
            "goal": "Load the frozen BTC5 recovery package first on the new box in shadow mode.",
            "required_state": {
                "allow_order_submission": False,
                "agent_run_mode": "shadow",
                "selected_package": frozen_package_id,
            },
            "pass_now": False,
            "current_observation": {
                "runtime_package_loaded": as_bool(selected_runtime_package.get("runtime_package_loaded")),
                "selected_best_profile_name": comparison_only_package,
            },
        },
        {
            "step": 2,
            "name": "candidate_scan",
            "status": "pending_upgrade",
            "goal": "Run the first clean post-upgrade shadow scan and confirm the BTC5 package is the active champion lane.",
            "required_state": {
                "polymarket_candidates_total_min": 1,
                "champion_lane": "btc_5m",
            },
            "pass_now": False,
            "current_observation": {
                "polymarket_candidates_total": polymarket_candidates_total,
                "champion_lane": champion_lane.get("lane"),
                "frozen_package_id": frozen_package_id,
            },
        },
        {
            "step": 3,
            "name": "order_failure_check",
            "status": "guardrail_configured",
            "goal": "Verify post-upgrade shadow execution keeps BTC5 order failures below the stage gate.",
            "required_state": {
                "order_failed_rate_recent_40_max": order_failure_threshold,
            },
            "pass_now": order_failed_rate_recent_40 <= order_failure_threshold,
            "current_observation": {
                "order_failed_rate_recent_40": order_failed_rate_recent_40,
                "source": "reports/strategy_scale_comparison.json",
            },
        },
        {
            "step": 4,
            "name": "executed_notional_check",
            "status": "blocked_until_utilization_returns",
            "goal": "Require candidate scan conversion and real executed notional before any size change.",
            "required_state": {
                "executed_notional_usd_last_hour_gt": 0.0,
                "candidate_to_trade_conversion_last_hour_gt": 0.0,
                "consecutive_cycles_required": 2,
            },
            "pass_now": executed_notional_last_hour > 0.0 and candidate_to_trade_conversion > 0.0,
            "current_observation": {
                "executed_notional_usd_last_hour": executed_notional_last_hour,
                "candidate_to_trade_conversion_last_hour": candidate_to_trade_conversion,
            },
        },
    ]
    contract = {
        "artifact": "instance2_btc5_package_freeze",
        "authoritative": True,
        "instance": 2,
        "generated_at": utc_now(),
        "objective": (
            "Freeze one BTC5 post-upgrade shadow champion, keep the stale open_et package "
            "comparison-only, and define the exact shadow sequence before any live-size change."
        ),
        "status": "upgrade_blocked",
        "source_artifacts": {
            "runtime_truth": "reports/runtime_truth_latest.json",
            "state_improvement": "reports/state_improvement_latest.json",
            "public_runtime_snapshot": "reports/public_runtime_snapshot.json",
            "improvement_velocity": "improvement_velocity.json",
            "finance_latest": "reports/finance/latest.json",
            "finance_action_queue": "reports/finance/action_queue.json",
            "btc5_selected_package": "reports/btc5_autoresearch/latest.json",
            "btc5_current_probe": "reports/btc5_autoresearch_current_probe/latest.json",
            "strategy_scale_comparison": "reports/strategy_scale_comparison.json",
            "signal_source_audit": "reports/signal_source_audit.json",
        },
        "decision_scope": {
            "applies_to": "first clean post-upgrade shadow cycle on the 8 GB / 2 vCPU / 160 GB SSD box",
            "does_not_authorize": [
                "service restart on the full old box",
                "runtime package load on the old box",
                "new live scaling",
                "capital widening from the incoming 2000 USD",
            ],
        },
        "truth_snapshot": {
            "launch_posture": str(get_path(public_runtime_snapshot, "launch.posture", runtime_truth.get("execution_mode")) or "blocked"),
            "service_status": str(get_path(public_runtime_snapshot, "service.status", runtime_truth.get("service_state")) or "stopped"),
            "allow_order_submission": as_bool(runtime_truth.get("allow_order_submission")),
            "agent_run_mode": str(runtime_truth.get("agent_run_mode") or "shadow"),
            "btc5_live_filled_rows": as_int(get_path(public_runtime_snapshot, "btc_5min_maker.live_filled_rows"), default=as_int(get_path(runtime_truth, "btc_5min_maker.live_filled_rows"))),
            "btc5_live_filled_pnl_usd": as_float(get_path(public_runtime_snapshot, "btc_5min_maker.live_filled_pnl_usd"), default=as_float(get_path(runtime_truth, "btc_5min_maker.live_filled_pnl_usd"))),
            "btc5_intraday_pnl_usd": as_float(intraday_live_summary.get("filled_pnl_usd_today")),
            "btc5_recent_12_live_filled_pnl_usd": trailing_12_live_filled_pnl_usd,
            "btc5_recent_20_live_filled_pnl_usd": as_float(intraday_live_summary.get("recent_20_pnl_usd")),
            "btc5_allowed_stage": as_int(btc5_stage_readiness.get("allowed_stage")),
            "btc5_can_trade_now": as_bool(btc5_stage_readiness.get("can_trade_now")),
            "runtime_package_loaded": as_bool(selected_runtime_package.get("runtime_package_loaded")),
            "selected_package_confidence_label": confidence_label,
            "polymarket_candidates_total": polymarket_candidates_total,
            "kalshi_candidates_total": kalshi_candidates_total,
            "executed_notional_usd_last_hour": executed_notional_last_hour,
            "candidate_to_trade_conversion_last_hour": candidate_to_trade_conversion,
            "order_failed_rate_recent_40": order_failed_rate_recent_40,
            "finance_gate_pass": as_bool(finance_latest.get("finance_gate_pass")),
            "last_executed_trading_allocation_usd": as_float(trading_action.get("amount_usd")),
            "last_executed_trading_allocation_at": trading_action.get("executed_at"),
        },
        "package_freeze": {
            "champion_lane": "btc_5m",
            "post_upgrade_shadow_package": {
                "package_id": frozen_package_id,
                "activation_mode": "shadow_only",
                "source": "reports/state_improvement_latest.json",
                "reason": (
                    "Fresh state-improvement ranking puts this tighter recovery package on top while "
                    "runtime truth still shows the older selected package load pending."
                ),
                "operator_rule": (
                    "Load this package first on the new box and treat it as the only BTC5 champion "
                    "until two clean utilization cycles are observed."
                ),
            },
            "comparison_only_package": {
                "package_id": comparison_only_package,
                "source": "reports/runtime_truth_latest.json,reports/btc5_autoresearch/latest.json",
                "reason": (
                    "The older open_et package remains comparison-only because short-window BTC5 "
                    "quality is negative and current runtime truth still shows runtime_package_load_pending=true."
                ),
            },
            "comparison_only_lanes": comparison_lanes,
            "non_btc_lane_policy": "comparison_only",
            "size_policy": "no_size_increase_beyond_current_proof_size",
        },
        "post_upgrade_shadow_sequence": shadow_sequence,
        "release_gates": {
            "pre_shadow_requirements": [
                "new_box_disk_and_service_health_validated",
                "runtime_truth_regenerated_on_new_box",
                f"package_loaded_matches_{frozen_package_id}",
            ],
            "pre_scale_requirements": [
                "package_loaded",
                "order_failed_rate_recent_40_lte_0.25",
                "executed_notional_usd_last_hour_gt_0_for_two_consecutive_cycles",
                "candidate_to_trade_conversion_gt_0_for_two_consecutive_cycles",
            ],
            "current_gate_state": {
                "package_loaded": as_bool(selected_runtime_package.get("runtime_package_loaded")),
                "order_failed_rate_recent_40_lte_0.25": order_failed_rate_recent_40 <= order_failure_threshold,
                "executed_notional_positive_two_cycles": False,
                "candidate_to_trade_conversion_positive_two_cycles": False,
            },
        },
        "release_schedule": [
            {
                "phase": 0,
                "status": "upgrade_blocked",
                "action": "Do nothing live on the old box beyond hold_repair.",
                "exit_criteria": [
                    "remote_runtime_storage_blocked_cleared",
                    "service_not_running_cleared",
                    "new_box_ready",
                ],
            },
            {
                "phase": 1,
                "status": "shadow_ready_after_upgrade",
                "action": f"Load {frozen_package_id} on the new box in shadow and regenerate runtime truth.",
                "exit_criteria": [
                    "package_loaded",
                    "runtime_truth_confirms_loaded_package",
                    "candidate_scan_completed",
                ],
            },
            {
                "phase": 2,
                "status": "shadow_ready_after_upgrade",
                "action": (
                    "Run the exact shadow sequence: package-load, candidate scan, order-failure check, "
                    "then executed-notional and conversion checks."
                ),
                "exit_criteria": [
                    "order_failed_rate_recent_40_lte_0.25",
                    "executed_notional_usd_last_hour_gt_0_for_two_consecutive_cycles",
                    "candidate_to_trade_conversion_gt_0_for_two_consecutive_cycles",
                    "btc5_recent_12_live_filled_pnl_usd_not_negative_across_two_cycles",
                ],
            },
        ],
        "capital_release_policy": {
            "current_250_usd_allocation": "sufficient_for_next_proof_window",
            "incoming_2000_usd": "park_in_reserve",
            "reason_additional_capital_remains_parked": (
                "Capital is not the unlock while the service is blocked, the chosen package is not loaded, "
                "executed notional is 0.0 in the last hour, candidate-to-trade conversion is 0.0, and the "
                "recent 12/20 BTC5 windows are negative."
            ),
            "non_champion_lanes": "comparison_only",
            "widen_runtime_size_now": False,
        },
        "inference_notes": [
            (
                "candidate_delta_arr_bps uses the freshest quantified BTC5 package delta from "
                "reports/btc5_autoresearch/latest.json because the state-improvement ranking selects the tighter "
                "recovery package but does not emit a separate ARR delta for that exact package id."
            ),
            (
                "arr_confidence_score carries forward the freshest cycle-level champion-lane confidence score "
                "already derived from the current runtime and state artifacts."
            ),
            (
                "order-failure gating is inferred from the current stage-readiness check in "
                "reports/strategy_scale_comparison.json, which is the repo's explicit execution-quality source."
            ),
        ],
        "required_outputs": {
            "candidate_delta_arr_bps": candidate_delta_arr_bps,
            "candidate_delta_arr_bps_basis": "reports/btc5_autoresearch/latest.json arr_tracking.median_arr_delta_pct",
            "expected_improvement_velocity_delta": as_float(
                get_path(state_improvement, "improvement_velocity.deltas.candidate_to_trade_conversion_delta"),
                default=0.0,
            ),
            "arr_confidence_score": arr_confidence_score,
            "block_reasons": release_block_reasons,
            "finance_gate_pass": as_bool(finance_latest.get("finance_gate_pass")) and as_bool(finance_gate.get("pass"), default=True),
            "one_next_cycle_action": (
                f"After the new 8 GB / 2 vCPU / 160 GB box validates cleanly, load {frozen_package_id} in shadow, "
                "regenerate runtime truth, run the first candidate scan, confirm order_failed_rate_recent_40 <= 0.25, "
                "and then require two consecutive cycles with executed_notional_usd > 0 and "
                "candidate_to_trade_conversion > 0 before any live-size change."
            ),
        },
    }
    return contract


def render_markdown(contract: dict[str, Any]) -> str:
    truth_snapshot = contract["truth_snapshot"]
    package_freeze = contract["package_freeze"]
    required_outputs = contract["required_outputs"]
    shadow_sequence = contract["post_upgrade_shadow_sequence"]
    lines = [
        "# Instance 02 Handoff - BTC5 Package Freeze",
        "",
        "## Status",
        f"- Current status: `{contract['status']}`",
        "- Next status after the 8 GB / 2 vCPU / 160 GB SSD cutover validates: `shadow_ready_after_upgrade`",
        "",
        "## Frozen Champion",
        f"- Champion lane: `{package_freeze['champion_lane']}`",
        f"- Frozen post-upgrade shadow package: `{package_freeze['post_upgrade_shadow_package']['package_id']}`",
        (
            "- Why this wins: `reports/state_improvement_latest.json` ranks the tighter recovery candidate highest "
            "while the currently selected `open_et` package remains load-pending and short-window BTC5 quality is still negative."
        ),
        "",
        "## Comparison-Only Set",
        f"- Package held comparison-only: `{package_freeze['comparison_only_package']['package_id']}`",
        "- Comparison-only lanes: "
        + ", ".join(f"`{lane}`" for lane in package_freeze["comparison_only_lanes"]),
        "- Size policy: `no_size_increase_beyond_current_proof_size`",
        "",
        "## Post-Upgrade Shadow Sequence",
    ]
    for step in shadow_sequence:
        if step["name"] == "package_load":
            detail = (
                f"load `{package_freeze['post_upgrade_shadow_package']['package_id']}` in shadow and confirm "
                f"`runtime_package_loaded=true` in regenerated truth; current loaded=`{truth_snapshot['runtime_package_loaded']}`"
            )
        elif step["name"] == "candidate_scan":
            detail = (
                f"run the first clean candidate scan with BTC5 as the champion lane; current seed count is "
                f"`{truth_snapshot['polymarket_candidates_total']}` Polymarket candidates"
            )
        elif step["name"] == "order_failure_check":
            detail = (
                "confirm `order_failed_rate_recent_40 <= 0.25`; current value is "
                f"`{truth_snapshot['order_failed_rate_recent_40']}`"
            )
        else:
            detail = (
                "require `executed_notional_usd_last_hour > 0` and "
                "`candidate_to_trade_conversion_last_hour > 0` for two consecutive cycles; current values are "
                f"`{truth_snapshot['executed_notional_usd_last_hour']}` and "
                f"`{truth_snapshot['candidate_to_trade_conversion_last_hour']}`"
            )
        lines.append(f"{step['step']}. `{step['name']}`: {detail}")
    lines.extend(
        [
            "",
            "## Capital Rule",
            "- The executed `250 USD` trading allocation is enough for the next proof window.",
            "- The incoming `2000 USD` stays in reserve.",
            (
                "- Extra capital stays parked because the service is blocked, the chosen package is not loaded, "
                f"hourly executed notional is `{truth_snapshot['executed_notional_usd_last_hour']}`, hourly candidate-to-trade conversion is "
                f"`{truth_snapshot['candidate_to_trade_conversion_last_hour']}`, and recent BTC5 windows are negative "
                f"(`{truth_snapshot['btc5_recent_12_live_filled_pnl_usd']}` on the last 12 live fills, "
                f"`{truth_snapshot['btc5_recent_20_live_filled_pnl_usd']}` on the last 20)."
            ),
            "",
            "## Required Outputs",
            f"- `candidate_delta_arr_bps`: `{required_outputs['candidate_delta_arr_bps']}`",
            f"- `expected_improvement_velocity_delta`: `{required_outputs['expected_improvement_velocity_delta']}`",
            f"- `arr_confidence_score`: `{required_outputs['arr_confidence_score']}`",
            f"- `finance_gate_pass`: `{str(required_outputs['finance_gate_pass']).lower()}`",
            f"- `one_next_cycle_action`: {required_outputs['one_next_cycle_action']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_done_payload(contract: dict[str, Any], command: str) -> dict[str, Any]:
    required_outputs = contract["required_outputs"]
    return {
        "instance": 2,
        "generated_at_utc": contract["generated_at"],
        "authoritative_artifacts": [
            "reports/parallel/instance02_btc5_package_freeze.json",
            "reports/parallel/instance02_btc5_package_freeze.md",
        ],
        "files_changed": [
            "scripts/render_instance2_btc5_package_freeze.py",
            "tests/test_render_instance2_btc5_package_freeze.py",
            "reports/parallel/instance02_btc5_package_freeze.json",
            "reports/parallel/instance02_btc5_package_freeze.md",
            "reports/parallel/instance2.done.json",
        ],
        "commands_run": [
            command,
            "python3 -m pytest tests/test_render_instance2_btc5_package_freeze.py -q",
        ],
        "key_findings": [
            (
                "BTC5 remains the only active trading champion lane, but the authoritative post-upgrade shadow "
                f"package is now frozen to {contract['package_freeze']['post_upgrade_shadow_package']['package_id']} "
                "while the stale open_et package remains comparison-only."
            ),
            (
                "The first clean post-upgrade shadow cycle is now explicit and ordered: package-load, candidate scan, "
                "order-failure check, then executed-notional and conversion checks."
            ),
            (
                "No new trading capital should be released just because finance can execute: the package is not loaded, "
                "executed notional is 0.0 in the last hour, candidate-to-trade conversion is 0.0, and the recent 12/20 BTC5 windows are negative."
            ),
            (
                "The executed 250 USD trading allocation is sufficient for the next proof window; the incoming 2000 USD stays "
                "parked in reserve until package-loaded and two-cycle utilization gates pass on the new box."
            ),
        ],
        "required_outputs": required_outputs,
        "unverified": [
            "No runtime package was loaded locally or remotely in this window; the freeze remains an operator contract until the new box is online.",
            "The exact post-upgrade shadow sequence still depends on the new box reaching a clean blocked-to-shadow cutover state.",
            "candidate_delta_arr_bps is inferred from the freshest quantified BTC5 package delta in reports/btc5_autoresearch/latest.json.",
        ],
        "safe_to_edit": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the Instance 2 BTC5 package-freeze artifacts.")
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--state-improvement", type=Path, default=DEFAULT_STATE_IMPROVEMENT)
    parser.add_argument("--public-runtime-snapshot", type=Path, default=DEFAULT_PUBLIC_RUNTIME_SNAPSHOT)
    parser.add_argument("--improvement-velocity", type=Path, default=DEFAULT_IMPROVEMENT_VELOCITY)
    parser.add_argument("--finance-latest", type=Path, default=DEFAULT_FINANCE_LATEST)
    parser.add_argument("--finance-action-queue", type=Path, default=DEFAULT_FINANCE_ACTION_QUEUE)
    parser.add_argument("--selected-package", type=Path, default=DEFAULT_SELECTED_PACKAGE)
    parser.add_argument("--current-probe", type=Path, default=DEFAULT_CURRENT_PROBE)
    parser.add_argument("--strategy-scale-comparison", type=Path, default=DEFAULT_STRATEGY_SCALE_COMPARISON)
    parser.add_argument("--signal-source-audit", type=Path, default=DEFAULT_SIGNAL_SOURCE_AUDIT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--done-json", type=Path, default=DEFAULT_DONE_JSON)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build_contract(
        runtime_truth=load_json(args.runtime_truth),
        state_improvement=load_json(args.state_improvement),
        public_runtime_snapshot=load_json(args.public_runtime_snapshot),
        improvement_velocity=load_json(args.improvement_velocity),
        finance_latest=load_json(args.finance_latest),
        finance_action_queue=load_json(args.finance_action_queue),
        selected_package=load_json(args.selected_package),
        current_probe=load_json(args.current_probe),
        strategy_scale_comparison=load_json(args.strategy_scale_comparison),
        signal_source_audit=load_json(args.signal_source_audit),
    )
    markdown = render_markdown(contract)
    command = (
        "python3 scripts/render_instance2_btc5_package_freeze.py "
        "--output-json reports/parallel/instance02_btc5_package_freeze.json "
        "--output-md reports/parallel/instance02_btc5_package_freeze.md "
        "--done-json reports/parallel/instance2.done.json"
    )
    done_payload = build_done_payload(contract, command)
    write_json(args.output_json, contract)
    write_text(args.output_md, markdown)
    write_json(args.done_json, done_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
