"""Autoprompt model-budget planning for the finance control plane."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

DEFAULT_SINGLE_ACTION_CAP_USD = 250.0
DEFAULT_MONTHLY_COMMITMENT_CAP_USD = 1000.0
DEFAULT_PROGRAM_CAP_USD = 800.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pilot_actions() -> list[dict[str, Any]]:
    return [
        {
            "action_key": "allocate::autoprompt_api_credits_pilot",
            "action_type": "buy_tool_or_data",
            "bucket": "buy_tool_or_data",
            "title": "Queue autoprompt API credits pilot",
            "amount_usd": 120.0,
            "monthly_commitment_usd": 120.0,
            "priority_score": 89.0,
            "destination": "autoprompt_control_plane",
            "vendor": "api_credits_pool",
            "mode_requested": "live_spend",
            "reason": "Fund API-first worker and judge calls for the bounded autoprompt pilot without increasing trading treasury exposure.",
            "rollback": "Cancel the credit top-up and freeze new autoprompt runs if model cost per validated artifact exceeds plan or the cycle remains blocked for two consecutive retries.",
            "idempotency_key": "allocate::autoprompt_api_credits_pilot",
            "requires_whitelist": False,
            "metadata": {
                "budget_program": "autoprompt_phase1",
                "operating_point": "pilot",
                "category": "api_credits",
                "expected_arr_impact_bps": 85,
                "expected_information_gain_30d": 38.0,
                "expected_cycle_throughput_gain_pct": 8.0,
                "confidence": 0.81,
                "rollback_trigger": "cost_per_validated_artifact_above_plan_or_two_blocked_retries",
                "source_artifacts": [
                    "autoprompting.md",
                    "docs/ops/finance_control_plane.md",
                    "reports/finance/latest.json",
                    "reports/runtime_truth_latest.json",
                ],
            },
        },
        {
            "action_key": "allocate::autoprompt_eval_compute_pilot",
            "action_type": "buy_tool_or_data",
            "bucket": "buy_tool_or_data",
            "title": "Queue autoprompt comparison-bench compute pilot",
            "amount_usd": 50.0,
            "monthly_commitment_usd": 50.0,
            "priority_score": 74.0,
            "destination": "autoprompt_control_plane",
            "vendor": "comparison_bench_compute",
            "mode_requested": "live_spend",
            "reason": "Reserve cheap comparison and replay capacity so the control plane can benchmark candidate prompts before any merge or deploy recommendation.",
            "rollback": "Drop back to local-only comparisons if benchmark win-rate deltas stay inconclusive after the first full pilot cycle.",
            "idempotency_key": "allocate::autoprompt_eval_compute_pilot",
            "requires_whitelist": False,
            "metadata": {
                "budget_program": "autoprompt_phase1",
                "operating_point": "pilot",
                "category": "compute",
                "expected_arr_impact_bps": 60,
                "expected_information_gain_30d": 29.0,
                "expected_cycle_throughput_gain_pct": 4.0,
                "confidence": 0.77,
                "rollback_trigger": "comparison_bench_not_decisive_after_pilot_cycle",
                "source_artifacts": [
                    "autoprompting.md",
                    "reports/finance/latest.json",
                ],
            },
        },
        {
            "action_key": "allocate::autoprompt_artifact_io_pilot",
            "action_type": "buy_tool_or_data",
            "bucket": "buy_tool_or_data",
            "title": "Queue autoprompt artifact retention and I/O pilot",
            "amount_usd": 30.0,
            "monthly_commitment_usd": 30.0,
            "priority_score": 58.0,
            "destination": "autoprompt_control_plane",
            "vendor": "artifact_retention_io",
            "mode_requested": "live_spend",
            "reason": "Cover artifact retention, replay packets, and small-volume comparison output transport needed for deterministic judging.",
            "rollback": "Return to minimal retention and prune non-critical artifacts if throughput stays flat or retention costs drift above plan.",
            "idempotency_key": "allocate::autoprompt_artifact_io_pilot",
            "requires_whitelist": False,
            "metadata": {
                "budget_program": "autoprompt_phase1",
                "operating_point": "pilot",
                "category": "artifact_io",
                "expected_arr_impact_bps": 45,
                "expected_information_gain_30d": 18.0,
                "expected_cycle_throughput_gain_pct": 2.0,
                "confidence": 0.73,
                "rollback_trigger": "artifact_retention_cost_drift_or_no_throughput_gain",
                "source_artifacts": [
                    "autoprompting.md",
                    "reports/finance/latest.json",
                ],
            },
        },
    ]


def _operating_points() -> list[dict[str, Any]]:
    return [
        {
            "operating_point": "pilot",
            "monthly_budget_usd": 200.0,
            "recommended_now": True,
            "expected_arr_impact_bps": 190,
            "expected_information_gain_30d": 85.0,
            "expected_cycle_throughput_gain_pct": 14.0,
            "confidence": 0.78,
            "allocation_mix": [
                {"category": "api_credits", "amount_usd": 120.0},
                {"category": "compute", "amount_usd": 50.0},
                {"category": "artifact_io", "amount_usd": 30.0},
            ],
            "reason": "Smallest policy-compliant package that funds API-first research throughput while leaving trading treasury expansion blocked and separate.",
        },
        {
            "operating_point": "active",
            "monthly_budget_usd": 400.0,
            "recommended_now": False,
            "expected_arr_impact_bps": 260,
            "expected_information_gain_30d": 121.0,
            "expected_cycle_throughput_gain_pct": 22.0,
            "confidence": 0.74,
            "allocation_mix": [
                {"category": "api_credits", "amount_usd": 180.0},
                {"category": "compute", "amount_usd": 100.0},
                {"category": "artifact_io", "amount_usd": 40.0},
                {"category": "judge_arbitration_buffer", "amount_usd": 80.0},
            ],
            "reason": "Adds more aggressive benchmarking and judge arbitration only after the pilot produces clean cycle truth and stable win/loss comparisons.",
        },
        {
            "operating_point": "max",
            "monthly_budget_usd": 800.0,
            "recommended_now": False,
            "expected_arr_impact_bps": 340,
            "expected_information_gain_30d": 182.0,
            "expected_cycle_throughput_gain_pct": 31.0,
            "confidence": 0.69,
            "allocation_mix": [
                {"category": "api_credits", "amount_usd": 250.0},
                {"category": "compute", "amount_usd": 180.0},
                {"category": "artifact_io", "amount_usd": 70.0},
                {"category": "judge_arbitration_buffer", "amount_usd": 150.0},
                {"category": "benchmark_burst", "amount_usd": 150.0},
            ],
            "reason": "Reserved ceiling for a higher-volume cycle once the controller, worker packets, and judge loop are already proving value and staying inside per-action caps.",
        },
    ]


def queued_commitments(action_queue: dict[str, Any]) -> float:
    total = 0.0
    for action in action_queue.get("actions", []):
        if not isinstance(action, dict):
            continue
        if str(action.get("status") or "").lower() not in {"queued", "shadowed", "executed"}:
            continue
        total += _safe_float(action.get("monthly_commitment_usd"), 0.0)
    return round(total, 2)


def build_model_budget_plan(
    *,
    finance_latest: dict[str, Any],
    action_queue: dict[str, Any],
    runtime_truth: dict[str, Any],
    now: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    generated_at = now or utc_now()
    finance_gate_pass = bool(finance_latest.get("finance_gate_pass"))
    rollout_gates = finance_latest.get("rollout_gates") if isinstance(finance_latest.get("rollout_gates"), dict) else {}
    ready_for_live_spend = bool(rollout_gates.get("ready_for_live_spend"))
    current_commitments = queued_commitments(action_queue)
    available_commitment_headroom = round(
        max(DEFAULT_MONTHLY_COMMITMENT_CAP_USD - current_commitments, 0.0),
        2,
    )
    capital_ready = _safe_float((finance_latest.get("totals") or {}).get("capital_ready_to_deploy_usd"), 0.0)

    queue_status = "queued" if finance_gate_pass and ready_for_live_spend else "shadowed"
    queued_actions: list[dict[str, Any]] = []
    for action in _pilot_actions():
        queue_action = deepcopy(action)
        queue_action["status"] = queue_status
        queued_actions.append(queue_action)

    pilot_monthly_total = round(sum(_safe_float(item["monthly_commitment_usd"]) for item in queued_actions), 2)
    policy_ok = (
        pilot_monthly_total <= DEFAULT_PROGRAM_CAP_USD
        and pilot_monthly_total <= available_commitment_headroom
        and all(_safe_float(item["amount_usd"]) <= DEFAULT_SINGLE_ACTION_CAP_USD for item in queued_actions)
    )

    runtime_stage = runtime_truth.get("btc5_stage_readiness") if isinstance(runtime_truth.get("btc5_stage_readiness"), dict) else {}
    block_reasons = [
        "llm_budget_not_queued",
        "trading_treasury_expansion_blocked_but_research_spend_not_split",
    ]

    plan = {
        "schema_version": "model_budget_plan.v1",
        "generated_at": generated_at,
        "instance": "instance_5",
        "objective": "Stage explicit model and compute budget for autoprompt autonomy without mixing research/tooling spend with trading treasury expansion.",
        "required_outputs": {
            "candidate_delta_arr_bps": 190,
            "expected_improvement_velocity_delta": "+14%",
            "arr_confidence_score": 0.78,
            "block_reasons": block_reasons,
            "finance_gate_pass": finance_gate_pass,
            "one_next_cycle_action": "queue the pilot model-budget package under the finance caps",
        },
        "policy_snapshot": {
            "single_action_cap_usd": DEFAULT_SINGLE_ACTION_CAP_USD,
            "monthly_new_commitment_cap_usd": DEFAULT_MONTHLY_COMMITMENT_CAP_USD,
            "program_default_cap_usd": DEFAULT_PROGRAM_CAP_USD,
            "capital_ready_to_deploy_usd": round(capital_ready, 2),
            "current_monthly_commitments_usd": current_commitments,
            "remaining_commitment_headroom_usd": available_commitment_headroom,
            "finance_state": finance_latest.get("finance_state"),
            "capital_expansion_only_hold": bool(finance_latest.get("capital_expansion_only_hold")),
            "treasury_gate_pass": bool(finance_latest.get("treasury_gate_pass")),
            "research_spend_mode_allowed": queue_status == "queued",
        },
        "spend_split": {
            "trading_treasury": {
                "status": "blocked_for_expansion",
                "reason": (finance_latest.get("finance_gate") or {}).get("reason"),
                "remediation": (finance_latest.get("finance_gate") or {}).get("remediation"),
            },
            "research_and_tooling": {
                "status": "queue_ready" if queue_status == "queued" else "shadow_only",
                "mode_requested": "live_spend",
                "reason": "Research/tooling spend remains policy-compliant even while live treasury expansion stays blocked.",
            },
        },
        "provider_preference": {
            "ordered_priority": [
                "api_credits",
                "local_or_cheap_comparison_compute",
                "artifact_retention_io",
                "judge_arbitration_buffer",
                "benchmark_burst",
            ],
            "deferred_items": [
                {
                    "item": "seat_automation_bridge",
                    "decision": "deny_for_phase1",
                    "reason": "Phase 1 prefers API-first credits and comparison-only compute before any seat-driven bridge.",
                }
            ],
        },
        "operating_points": _operating_points(),
        "queue_package": {
            "operating_point": "pilot",
            "status": queue_status,
            "monthly_total_usd": pilot_monthly_total,
            "policy_compliant": policy_ok,
            "actions": queued_actions,
        },
        "assumptions": [
            "No canonical dispatch-packet compute manifest exists yet, so provider and compute needs are inferred from autoprompting.md phase-1 control-plane surfaces.",
            "Trading treasury expansion remains blocked and must not be used as a reason to suppress research/tooling queue construction.",
            "The existing finance action queue is the machine contract for queued spend recommendations, even before finance execute persists the actions into the SQLite store.",
        ],
        "source_snapshot": {
            "finance_latest_generated_at": finance_latest.get("generated_at"),
            "action_queue_generated_at": action_queue.get("generated_at"),
            "runtime_truth_generated_at": runtime_truth.get("generated_at"),
            "baseline_live_allowed": bool(runtime_stage.get("baseline_live_allowed")),
            "stage_upgrade_ready": bool(runtime_stage.get("ready_for_stage_1")),
        },
    }
    return plan, queued_actions
