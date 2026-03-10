"""Render the finance control report from available machine artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nontrading.finance import (
    AllocationCandidate,
    FinanceAllocator,
    FinanceBucket,
    FinancePolicy,
    FinanceSnapshot,
    ResourceAskKind,
)
from nontrading.finance.models import utc_now


def write_json_artifact(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _finance_snapshot_totals(finance_snapshot: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(finance_snapshot, dict):
        return {}
    if isinstance(finance_snapshot.get("snapshot"), dict):
        totals = finance_snapshot["snapshot"].get("totals")
        if isinstance(totals, dict):
            return {key: _safe_float(value) for key, value in totals.items()}
    totals = finance_snapshot.get("totals")
    if isinstance(totals, dict):
        return {key: _safe_float(value) for key, value in totals.items()}
    finance_totals = finance_snapshot.get("finance_totals")
    if isinstance(finance_totals, dict):
        return {key: _safe_float(value) for key, value in finance_totals.items()}
    return {}


def _derive_finance_gate(
    finance_snapshot: dict[str, Any] | None,
    action_queue: dict[str, Any] | None,
) -> dict[str, Any]:
    last_execute = {}
    if isinstance(finance_snapshot, dict) and isinstance(finance_snapshot.get("last_execute"), dict):
        last_execute = finance_snapshot["last_execute"]
    elif isinstance(action_queue, dict) and isinstance(action_queue.get("last_execute"), dict):
        last_execute = action_queue["last_execute"]
    if last_execute:
        live_hold = last_execute.get("live_hold") if isinstance(last_execute.get("live_hold"), dict) else {}
        finance_gate_pass = bool(last_execute.get("finance_gate_pass"))
        status = str(
            live_hold.get("status")
            or ("pass" if finance_gate_pass else "hold_repair")
        ).strip().lower()
        return {
            "status": status,
            "pass": finance_gate_pass,
            "reason": live_hold.get("reason") or ("executed" if finance_gate_pass else "last_execute_blocked"),
            "blocked_action_key": live_hold.get("action_key"),
            "requested_mode": live_hold.get("requested_mode") or last_execute.get("requested_mode") or last_execute.get("mode"),
            "destination": live_hold.get("destination"),
            "policy_checks": live_hold.get("policy_checks") or last_execute.get("policy_checks") or {},
            "retry_at": live_hold.get("retry_at"),
            "retry_in_minutes": live_hold.get("retry_in_minutes"),
            "last_result_statuses": [
                str(item.get("status"))
                for item in last_execute.get("results") or []
                if isinstance(item, dict) and item.get("status")
            ],
        }
    if not isinstance(action_queue, dict):
        return {
            "status": "hold_repair",
            "pass": False,
            "reason": "finance_action_queue_missing",
            "blocked_action_key": None,
        }
    actions = action_queue.get("actions") or []
    for action in actions:
        if not isinstance(action, dict):
            continue
        metadata = action.get("metadata") or {}
        hold_reason = metadata.get("hold_reason")
        if hold_reason:
            return {
                "status": "hold_repair",
                "pass": False,
                "reason": str(hold_reason),
                "blocked_action_key": action.get("action_key"),
                "requested_mode": action.get("mode_requested"),
                "destination": action.get("destination"),
                "policy_checks": metadata.get("policy_checks") or {},
            }
    queued = sum(1 for action in actions if isinstance(action, dict) and action.get("status") == "queued")
    return {
        "status": "pass" if queued else "idle",
        "pass": bool(queued),
        "reason": "queue_ready" if queued else "no_pending_actions",
        "blocked_action_key": None,
    }


def _select_next_action(action_queue: dict[str, Any] | None, nontrading_status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(action_queue, dict):
        return None
    queued_actions = [
        action
        for action in (action_queue.get("actions") or [])
        if isinstance(action, dict) and str(action.get("status") or "").lower() == "queued"
    ]
    if not queued_actions:
        return None
    queued_actions.sort(key=lambda action: float(action.get("priority_score") or 0.0), reverse=True)
    action = queued_actions[0]
    next_action = {
        "action_key": action.get("action_key"),
        "bucket": action.get("bucket"),
        "destination": action.get("destination"),
        "amount_usd": _safe_float(action.get("amount_usd")),
        "status": "queued",
        "reason": action.get("reason"),
    }
    if action.get("bucket") == "fund_nontrading" and isinstance(nontrading_status, dict):
        blocking_reasons = [str(item) for item in nontrading_status.get("blocking_reasons") or [] if item]
        if not bool(nontrading_status.get("launchable")):
            next_action["status"] = "queued_until_launchable"
            next_action["blocking_reasons"] = blocking_reasons
            next_action["reason"] = (
                "JJ-N remains queued behind product-surface blockers."
            )
            next_action["retry_in_minutes"] = 30
    return next_action


def _allocation_summary(allocation: dict[str, Any]) -> dict[str, Any]:
    ranked_actions = allocation.get("ranked_actions") or []
    resource_asks = allocation.get("resource_asks") or []
    decisions = {"approve": 0, "ask": 0, "deny": 0}
    for row in ranked_actions:
        if not isinstance(row, dict):
            continue
        decision = str(row.get("decision") or "").lower()
        if decision in decisions:
            decisions[decision] += 1
    return {
        "candidate_count": len(ranked_actions),
        "resource_ask_count": len(resource_asks),
        "approved_candidate_count": decisions["approve"],
        "ask_candidate_count": decisions["ask"],
        "denied_candidate_count": decisions["deny"],
    }


def build_finance_control_report(
    *,
    policy: FinancePolicy,
    runtime_truth_path: Path,
    state_improvement_path: Path,
    nontrading_report_path: Path,
    nontrading_status_path: Path,
    finance_snapshot_path: Path,
    subscription_audit_path: Path,
    action_queue_path: Path,
    workflow_mining_summary_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_truth = _load_optional_json(runtime_truth_path) or {}
    state_improvement = _load_optional_json(state_improvement_path) or {}
    nontrading_report = _load_optional_json(nontrading_report_path) or {}
    nontrading_status = _load_optional_json(nontrading_status_path)
    finance_snapshot = _load_optional_json(finance_snapshot_path)
    subscription_audit = _load_optional_json(subscription_audit_path)
    action_queue = _load_optional_json(action_queue_path)
    workflow_mining = _load_optional_json(workflow_mining_summary_path)

    gaps: list[dict[str, str]] = []
    if finance_snapshot is None:
        gaps.append({"code": "finance_snapshot_missing", "detail": str(finance_snapshot_path)})
    if subscription_audit is None:
        gaps.append({"code": "subscription_audit", "detail": str(subscription_audit_path)})
    if action_queue is None:
        gaps.append({"code": "finance_action_queue", "detail": str(action_queue_path)})
    if workflow_mining is None:
        gaps.append({"code": "workflow_mining", "detail": str(workflow_mining_summary_path)})
    if not nontrading_status_path.exists():
        gaps.append({"code": "nontrading_status_missing", "detail": str(nontrading_status_path)})

    finance_totals = _finance_snapshot_totals(finance_snapshot)
    snapshot = FinanceSnapshot(
        liquid_cash_usd=finance_totals.get("deployable_cash_usd", finance_totals.get("capital_ready_to_deploy_usd", 0.0)),
        monthly_burn_usd=finance_totals.get("monthly_burn_usd", finance_totals.get("subscription_burn_monthly", 0.0)),
        illiquid_equity_usd=finance_totals.get("illiquid_position_value_usd", finance_totals.get("startup_equity_usd", 0.0)),
    )

    candidates: list[AllocationCandidate] = []
    if finance_snapshot is None:
        candidates.append(
            AllocationCandidate(
                candidate_id="buy_data_finance_imports",
                label="Buy finance imports/data",
                bucket=FinanceBucket.BUY_TOOL_OR_DATA,
                requested_amount_usd=50.0,
                expected_net_value_30d=0.0,
                expected_information_gain_30d=40.0,
                confidence=0.6,
                ask_kind=ResourceAskKind.DATA,
                blocker_removal_value=1.0,
                model_tier="routine_ingestion",
                model_minutes=5.0,
                model_provider="general_llm",
            )
        )
    allocator_input = (nontrading_report.get("allocator_input") or {}) if nontrading_report else {}
    required_budget = float(allocator_input.get("required_budget", 0.0) or 0.0)
    if required_budget > 0:
        candidates.append(
            AllocationCandidate(
                candidate_id="fund_nontrading_control_plane",
                label="Fund JJ-N control plane",
                bucket=FinanceBucket.FUND_NONTRADING,
                requested_amount_usd=required_budget,
                expected_net_value_30d=float(allocator_input.get("expected_net_cash_30d", 0.0) or 0.0),
                expected_information_gain_30d=10.0,
                confidence=float(allocator_input.get("confidence", 0.0) or 0.0),
                ask_kind=ResourceAskKind.EXPERIMENT,
                expected_arr_lift_30d=float(allocator_input.get("expected_net_cash_30d", 0.0) or 0.0),
                expected_arr_confidence_lift=max(0.0, 0.6 - float(allocator_input.get("confidence", 0.0) or 0.0)),
                blocker_removal_value=0.0,
                model_tier="structured_ranking",
                model_minutes=12.0,
                model_provider="general_llm",
            )
        )
    maker = runtime_truth.get("btc_5min_maker", {})
    live_rows = float(maker.get("live_filled_rows", 0.0) or 0.0)
    if live_rows > 0:
        recent_pnl = float(
            maker.get("fill_attribution", {}).get("recent_live_filled_summary", {}).get("pnl_usd", 0.0) or 0.0
        )
        candidates.append(
            AllocationCandidate(
                candidate_id="fund_trading_runtime",
                label="Fund trading runtime",
                bucket=FinanceBucket.FUND_TRADING,
                requested_amount_usd=100.0,
                expected_net_value_30d=recent_pnl,
                expected_information_gain_30d=min(live_rows / 10.0, 25.0),
                confidence=0.7,
                ask_kind=ResourceAskKind.CAPITAL,
                expected_arr_lift_30d=recent_pnl,
                expected_arr_confidence_lift=0.08,
                blocker_removal_value=0.0,
                model_tier="structured_ranking",
                model_minutes=18.0,
                model_provider="general_llm",
            )
        )

    allocation = FinanceAllocator(policy).allocate(snapshot=snapshot, candidates=candidates)
    allocation["summary"] = _allocation_summary(allocation)
    finance_gate = _derive_finance_gate(
        finance_snapshot if isinstance(finance_snapshot, dict) else None,
        action_queue,
    )
    next_action = _select_next_action(action_queue, nontrading_status)
    finance_totals_packet = {
        "free_cash_after_floor": allocation["finance_snapshot"]["free_cash_after_floor_usd"],
        "capital_ready_to_deploy_usd": allocation["finance_snapshot"]["capital_ready_to_deploy_usd"],
        "cash_reserve_floor_usd": allocation["finance_snapshot"]["reserve_floor_usd"],
        "ignored_illiquid_equity_usd": allocation["finance_snapshot"]["ignored_illiquid_equity_usd"],
    }

    latest = {
        "schema_version": "finance_control_report.v1",
        "generated_at": action_queue.get("generated_at") if isinstance(action_queue, dict) else utc_now(),
        "metrics": {
            "free_cash_after_floor": allocation["finance_snapshot"]["free_cash_after_floor_usd"],
            "capital_ready_to_deploy_usd": allocation["finance_snapshot"]["capital_ready_to_deploy_usd"],
        },
        "finance_gate": finance_gate,
        "finance_gate_pass": finance_gate["pass"],
        "resource_asks": allocation["resource_asks"],
        "allocator_rankings_batch": {
            "generated_at": action_queue.get("generated_at") if isinstance(action_queue, dict) else None,
            "candidate_rankings": allocation["ranked_actions"],
        },
        "finance_totals": finance_totals_packet,
        "allocation_plan_summary": allocation["summary"],
        "cycle_budget_ledger": allocation["cycle_budget_ledger"],
        "last_execute": (
            finance_snapshot.get("last_execute")
            if isinstance(finance_snapshot, dict) and isinstance(finance_snapshot.get("last_execute"), dict)
            else None
        ),
        "one_next_cycle_action": next_action,
        "gaps": gaps,
        "allocation_plan": allocation,
        "inputs": {
            "state_improvement_present": bool(state_improvement),
            "runtime_truth_present": bool(runtime_truth),
            "nontrading_report_present": bool(nontrading_report),
        },
    }
    return latest, allocation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the finance control report from machine artifacts.")
    parser.add_argument("--root", default=".", help="Workspace root.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    finance_dir = root / "reports" / "finance"
    latest, allocation = build_finance_control_report(
        policy=FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0),
        runtime_truth_path=root / "reports" / "runtime_truth_latest.json",
        state_improvement_path=root / "reports" / "state_improvement_latest.json",
        nontrading_report_path=root / "reports" / "nontrading_public_report.json",
        nontrading_status_path=root / "reports" / "nontrading_first_dollar_status.json",
        finance_snapshot_path=finance_dir / "latest.json",
        subscription_audit_path=finance_dir / "subscription_audit.json",
        action_queue_path=finance_dir / "action_queue.json",
        workflow_mining_summary_path=root / "reports" / "agent_workflow_mining" / "summary.json",
    )
    write_json_artifact(allocation, finance_dir / "allocation_plan.json")
    write_json_artifact(latest, finance_dir / "latest.json")
    print(json.dumps({"latest": str(finance_dir / "latest.json"), "allocation": str(finance_dir / "allocation_plan.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
