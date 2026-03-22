from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.remote_cycle_common import (
    bool_or_none,
    dedupe_preserve_order,
    first_nonempty,
    int_or_none,
    load_json,
    relative_path_text,
)


_LEGACY_LANE_ID_MAP = {
    "btc5_live_baseline": "maker_bootstrap_live",
    "everything_else_no_spend": "everything_else",
    "weather_shadow_only": "weather",
}


def _canonical_lane_id(value: Any) -> str:
    lane_id = str(value or "").strip().lower()
    if not lane_id:
        return ""
    return _LEGACY_LANE_ID_MAP.get(lane_id, lane_id)


def _normalize_lane_verdicts(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, Any] = {}
    for raw_lane_id, verdict in payload.items():
        lane_id = _canonical_lane_id(raw_lane_id)
        if lane_id:
            normalized[lane_id] = verdict
    return normalized


def _normalize_lane_budgets(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, Any] = {}
    for raw_lane_id, budget in payload.items():
        lane_id = _canonical_lane_id(raw_lane_id)
        if not lane_id:
            continue
        if isinstance(budget, dict):
            normalized[lane_id] = {
                **budget,
                "lane_id": _canonical_lane_id(budget.get("lane_id") or lane_id) or lane_id,
            }
        else:
            normalized[lane_id] = budget
    return normalized


def _lane_verdicts_from_allocation_contract(payload: dict[str, Any]) -> dict[str, Any]:
    return _normalize_lane_verdicts(
        {
            "maker_bootstrap_live": payload.get("baseline_allocation_state"),
            "wallet_intel_directional_shadow": payload.get("wallet_intel_lane_state"),
            "weather": payload.get("weather_lane_state"),
            "everything_else": payload.get("other_lanes_state"),
        }
    )


def load_finance_gate_status(root: Path) -> dict[str, Any]:
    path = root / "reports" / "finance" / "latest.json"
    if not path.exists():
        return {
            "available": False,
            "finance_gate_pass": True,
            "reason": "finance_artifact_missing_assumed_pass",
            "remediation": None,
            "retry_at": None,
            "retry_in_minutes": None,
            "source": relative_path_text(root, path) or str(path),
        }

    payload = load_json(path, default={})
    if not isinstance(payload, dict):
        payload = {}
    last_execute = dict(payload.get("last_execute") or {})
    live_hold = dict(last_execute.get("live_hold") or {})
    finance_gate = dict(payload.get("finance_gate") or {})
    capital_expansion_policy = dict(payload.get("capital_expansion_policy") or {})
    allocation_contract = dict(payload.get("allocation_contract") or {})
    finance_lane_verdicts = _normalize_lane_verdicts(payload.get("finance_lane_verdicts") or payload.get("verdict") or {})
    finance_lane_budgets = _normalize_lane_budgets(
        payload.get("finance_lane_budgets")
        or payload.get("lanes")
        or (payload.get("bankroll") or {}).get("sleeves")
        or {}
    )
    if not finance_lane_verdicts:
        finance_lane_verdicts = _lane_verdicts_from_allocation_contract(allocation_contract)
    finance_state = str(
        first_nonempty(
            capital_expansion_policy.get("finance_state"),
            payload.get("finance_state"),
            live_hold.get("status"),
            "",
        )
    ).strip().lower()
    stage_cap = int_or_none(
        first_nonempty(
            capital_expansion_policy.get("stage_cap"),
            finance_gate.get("stage_cap"),
            allocation_contract.get("max_live_stage_cap"),
            payload.get("max_live_stage_cap"),
            payload.get("stage_cap"),
            None,
        )
    )
    treasury_gate_pass = bool_or_none(last_execute.get("finance_gate_pass"))
    if treasury_gate_pass is None:
        treasury_gate_pass = bool_or_none(payload.get("finance_gate_pass"))
    if treasury_gate_pass is None:
        treasury_gate_pass = bool_or_none(finance_gate.get("pass"))
    if treasury_gate_pass is None:
        treasury_gate_pass = True
    capital_expansion_only_hold = (
        finance_state == "hold_no_spend"
        and stage_cap is not None
        and stage_cap >= 1
    )
    explicit_hold_flag = bool_or_none(
        first_nonempty(
            capital_expansion_policy.get("capital_expansion_only_hold"),
            finance_gate.get("capital_expansion_only_hold"),
            payload.get("capital_expansion_only_hold"),
            None,
        )
    )
    if explicit_hold_flag is True:
        capital_expansion_only_hold = True
    hold_live_treasury = bool_or_none(capital_expansion_policy.get("hold_live_treasury"))
    if capital_expansion_only_hold or hold_live_treasury is True:
        treasury_gate_pass = False
    launch_gate_pass = bool(treasury_gate_pass or capital_expansion_only_hold)
    launch_gate_reason = first_nonempty(
        live_hold.get("reason"),
        finance_gate.get("reason"),
        last_execute.get("reason"),
        None,
    )
    launch_gate_remediation = first_nonempty(
        live_hold.get("remediation"),
        finance_gate.get("remediation"),
        None,
    )

    return {
        "available": True,
        "finance_gate_pass": bool(launch_gate_pass),
        "treasury_gate_pass": bool(treasury_gate_pass),
        "capital_expansion_only_hold": bool(capital_expansion_only_hold),
        "hold_live_treasury": bool(hold_live_treasury),
        "finance_state": finance_state or None,
        "stage_cap": stage_cap,
        "reason": launch_gate_reason,
        "remediation": launch_gate_remediation,
        "retry_at": first_nonempty(
            live_hold.get("retry_at"),
            None,
        ),
        "retry_in_minutes": int_or_none(live_hold.get("retry_in_minutes")),
        "requested_mode": first_nonempty(
            last_execute.get("requested_mode"),
            live_hold.get("requested_mode"),
            None,
        ),
        "max_live_stage_cap": int_or_none(
            first_nonempty(
                allocation_contract.get("max_live_stage_cap"),
                payload.get("max_live_stage_cap"),
                stage_cap,
                None,
            )
        ),
        "finance_lane_verdicts": finance_lane_verdicts,
        "finance_lane_budgets": finance_lane_budgets,
        "treasury_reason": first_nonempty(
            finance_gate.get("reason"),
            launch_gate_reason,
            None,
        ),
        "source": relative_path_text(root, path) or str(path),
    }


def build_finance_gate_status(*, root: Path) -> dict[str, Any]:
    action_queue_path = root / "reports" / "finance" / "action_queue.json"
    latest_path = root / "reports" / "finance" / "latest.json"
    canonical_status = load_finance_gate_status(root)
    queue_payload = load_json(action_queue_path, default={})
    latest_payload = load_json(latest_path, default={})
    actions = queue_payload.get("actions") if isinstance(queue_payload, dict) else []
    if not isinstance(actions, list):
        actions = []

    policy_hold_reasons: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        hold_reason = str(metadata.get("hold_reason") or "").strip()
        if hold_reason:
            policy_hold_reasons.append(hold_reason)
        action_status = str(action.get("status") or "").strip().lower()
        if action_status == "shadowed" and not hold_reason:
            policy_hold_reasons.append("shadowed_action_without_explicit_hold_reason")

    rollout_gates = latest_payload.get("rollout_gates") if isinstance(latest_payload, dict) else {}
    rollout_reasons = []
    if isinstance(rollout_gates, dict):
        rollout_reasons = [str(item) for item in list(rollout_gates.get("reasons") or []) if str(item).strip()]
    ready_for_live_treasury = (
        bool(rollout_gates.get("ready_for_live_treasury")) if isinstance(rollout_gates, dict) else None
    )
    allocation_contract = latest_payload.get("allocation_contract") if isinstance(latest_payload, dict) else {}
    if not isinstance(allocation_contract, dict):
        allocation_contract = {}
    baseline_live_trading_pass = bool_or_none(
        first_nonempty(
            latest_payload.get("baseline_live_trading_pass"),
            latest_payload.get("finance_gate_pass"),
            canonical_status.get("finance_gate_pass"),
            None,
        )
    )
    if baseline_live_trading_pass is None:
        baseline_state = str(allocation_contract.get("baseline_allocation_state") or "").strip().lower()
        if baseline_state == "baseline_allowed":
            baseline_live_trading_pass = True
        elif baseline_state == "baseline_blocked":
            baseline_live_trading_pass = False

    block_reasons = dedupe_preserve_order(policy_hold_reasons + rollout_reasons)
    if baseline_live_trading_pass is True:
        status = "pass"
    elif block_reasons:
        status = "hold"
    elif ready_for_live_treasury is True:
        status = "pass"
    elif ready_for_live_treasury is False:
        status = "hold"
        block_reasons = ["rollout_gate_not_ready_for_live_treasury"]
    else:
        status = "unknown"

    return {
        "status": status,
        "status_label": (
            f"hold:{block_reasons[0]}"
            if status == "hold" and block_reasons
            else ("pass" if status == "pass" else "unknown")
        ),
        "finance_gate_pass": (
            baseline_live_trading_pass
            if baseline_live_trading_pass is not None
            else canonical_status.get("finance_gate_pass")
        ),
        "baseline_live_trading_pass": baseline_live_trading_pass,
        "treasury_gate_pass": canonical_status.get("treasury_gate_pass"),
        "capital_expansion_only_hold": canonical_status.get("capital_expansion_only_hold"),
        "max_live_stage_cap": canonical_status.get("max_live_stage_cap"),
        "finance_lane_verdicts": canonical_status.get("finance_lane_verdicts") or {},
        "finance_lane_budgets": canonical_status.get("finance_lane_budgets") or {},
        "block_reasons": block_reasons,
        "source_artifacts": [
            "reports/finance/action_queue.json",
            "reports/finance/latest.json",
        ],
    }
