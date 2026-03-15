from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.remote_cycle_blockers import build_blocker_category_map
from scripts.remote_cycle_common import (
    bool_or_none,
    dedupe_preserve_order,
    first_nonempty,
    int_or_none,
    relative_path_text,
)
from scripts.remote_cycle_finance import load_finance_gate_status


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence_label_to_score(label: str) -> float:
    normalized = str(label or "").strip().lower()
    if normalized in {"high", "promote"}:
        return 0.85
    if normalized in {"medium", "moderate"}:
        return 0.65
    if normalized in {"low"}:
        return 0.35
    if normalized in {"missing", "unknown", ""}:
        return 0.15
    return 0.5


def _expected_agent_modes_for_execution(execution_mode: str) -> set[str]:
    normalized = str(execution_mode or "").strip().lower()
    compatible_agent_modes = {
        "shadow": {"shadow", "micro_live"},
        "micro_live": {"micro_live", "live"},
        "live": {"live"},
        "research": {"research"},
        "blocked": {"shadow", "research", "blocked"},
    }
    return compatible_agent_modes.get(normalized, {"micro_live", "live", "shadow", "research"})


def _build_launch_contract_checks(*, contract: dict[str, Any]) -> list[dict[str, Any]]:
    service_state = str(contract.get("service_state") or "unknown").strip().lower()
    agent_run_mode = str(contract.get("agent_run_mode") or "unknown").strip().lower()
    execution_mode = str(contract.get("execution_mode") or "unknown").strip().lower()
    launch_posture = str(contract.get("launch_posture") or "unknown").strip().lower()
    allow_order_submission = bool(contract.get("allow_order_submission"))
    order_submit_enabled = bool(contract.get("order_submit_enabled"))
    paper_trading = bool_or_none(contract.get("paper_trading"))
    checks: list[dict[str, Any]] = []

    def add_check(code: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "code": code,
                "pass": bool(passed),
                "detail": detail,
            }
        )

    add_check(
        "service_state_known",
        service_state not in {"", "unknown"},
        f"service_state={service_state}",
    )
    add_check(
        "mode_fields_known",
        agent_run_mode not in {"", "unknown"} and execution_mode not in {"", "unknown"},
        f"agent_run_mode={agent_run_mode}, execution_mode={execution_mode}",
    )
    add_check(
        "mode_alignment",
        agent_run_mode in _expected_agent_modes_for_execution(execution_mode),
        f"agent_run_mode={agent_run_mode}, execution_mode={execution_mode}",
    )
    add_check(
        "launch_order_alignment",
        not (launch_posture == "blocked" and order_submit_enabled),
        f"launch_posture={launch_posture}, order_submit_enabled={order_submit_enabled}",
    )
    add_check(
        "order_submit_requires_allow_submission",
        not (order_submit_enabled and not allow_order_submission),
        f"allow_order_submission={allow_order_submission}, order_submit_enabled={order_submit_enabled}",
    )
    add_check(
        "service_launch_order_consistency",
        not (service_state == "running" and launch_posture == "blocked" and allow_order_submission),
        (
            f"service_state={service_state}, launch_posture={launch_posture}, "
            f"allow_order_submission={allow_order_submission}"
        ),
    )
    expected_paper_by_mode = {
        "shadow": True,
        "research": True,
        "blocked": True,
        "micro_live": False,
        "live": False,
    }
    expected_paper = expected_paper_by_mode.get(execution_mode)
    add_check(
        "paper_mode_consistency",
        expected_paper is None or paper_trading is None or paper_trading == expected_paper,
        f"execution_mode={execution_mode}, paper_trading={paper_trading}, expected={expected_paper}",
    )
    add_check(
        "clear_posture_submit_consistency",
        not (
            launch_posture == "clear"
            and service_state == "running"
            and allow_order_submission
            and not order_submit_enabled
        ),
        (
            f"launch_posture={launch_posture}, service_state={service_state}, "
            f"allow_order_submission={allow_order_submission}, order_submit_enabled={order_submit_enabled}"
        ),
    )

    return checks


def _build_launch_state_bundle(runtime_truth_snapshot: dict[str, Any]) -> dict[str, Any]:
    service = dict(runtime_truth_snapshot.get("service") or {})
    launch = dict(runtime_truth_snapshot.get("launch") or {})
    deploy_evidence = dict(runtime_truth_snapshot.get("deploy_evidence") or {})
    deploy_validation = dict(deploy_evidence.get("validation") or {})
    selected_package = dict(runtime_truth_snapshot.get("btc5_selected_package") or {})
    stage_readiness = dict(runtime_truth_snapshot.get("btc5_stage_readiness") or {})
    launch_blocked_checks = {
        str(item).strip()
        for item in list(launch.get("blocked_checks") or [])
        if str(item).strip()
    }
    launch_blocked_reasons = [
        str(item).strip()
        for item in list(launch.get("blocked_reasons") or [])
        if str(item).strip()
    ]

    service_state = str(
        first_nonempty(
            runtime_truth_snapshot.get("service_state"),
            service.get("status"),
            "unknown",
        )
    ).strip() or "unknown"

    storage_blocked = bool_or_none(deploy_validation.get("storage_blocked"))
    if storage_blocked is None and "remote_runtime_storage_blocked" in launch_blocked_checks:
        storage_blocked = True
    if storage_blocked is True:
        storage_state = "blocked"
    elif storage_blocked is False:
        storage_state = "clear"
    else:
        storage_state = "unknown"

    storage_reason = deploy_validation.get("storage_block_reason")
    if not storage_reason and storage_blocked:
        storage_reason = next(
            (
                reason
                for reason in launch_blocked_reasons
                if "no space left on device" in reason.lower() or "storage" in reason.lower()
            ),
            None,
        )

    runtime_load_required = bool_or_none(selected_package.get("runtime_load_required"))
    runtime_package_loaded = bool_or_none(selected_package.get("runtime_package_loaded"))
    if runtime_load_required is False:
        package_load_state = "not_required"
    elif runtime_package_loaded is True:
        package_load_state = "loaded"
    elif runtime_package_loaded is False:
        package_load_state = "load_pending"
    else:
        package_load_state = "unknown"

    allowed_stage = int_or_none(stage_readiness.get("allowed_stage"))
    allowed_stage_label = str(
        stage_readiness.get("allowed_stage_label")
        or (f"stage_{allowed_stage}" if allowed_stage is not None else "unknown")
    )
    stage_blocking_checks = stage_readiness.get("trade_now_blocking_checks")
    if not stage_blocking_checks:
        stage_blocking_checks = stage_readiness.get("blocking_checks")

    return {
        "service": {
            "state": service_state,
            "systemctl_state": service.get("systemctl_state"),
            "checked_at": service.get("checked_at"),
        },
        "storage": {
            "state": storage_state,
            "blocked": storage_blocked,
            "reason": storage_reason,
            "validation_returncode": int_or_none(deploy_validation.get("returncode")),
            "checked_at": first_nonempty(
                deploy_evidence.get("generated_at"),
                runtime_truth_snapshot.get("generated_at"),
                service.get("checked_at"),
                None,
            ),
        },
        "package_load": {
            "state": package_load_state,
            "runtime_package_loaded": runtime_package_loaded,
            "runtime_load_required": runtime_load_required,
            "selected_package": first_nonempty(
                selected_package.get("selected_best_profile_name"),
                selected_package.get("selected_active_profile_name"),
                None,
            ),
            "deploy_recommendation": selected_package.get("selected_deploy_recommendation"),
            "confidence_label": selected_package.get("selected_package_confidence_label"),
            "generated_at": selected_package.get("generated_at"),
        },
        "stage": {
            "allowed_stage": allowed_stage,
            "allowed_stage_label": allowed_stage_label,
            "can_trade_now": bool_or_none(stage_readiness.get("can_trade_now")),
            "blocking_checks": [
                str(item)
                for item in list(stage_blocking_checks or [])
                if str(item).strip()
            ],
            "generated_at": stage_readiness.get("generated_at"),
        },
    }


def _bounded_stage1_restart_context(runtime_truth_snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_package = dict(runtime_truth_snapshot.get("btc5_selected_package") or {})
    deployment_confidence = dict(runtime_truth_snapshot.get("deployment_confidence") or {})
    capital = dict(runtime_truth_snapshot.get("capital") or {})
    wallet = dict(runtime_truth_snapshot.get("polymarket_wallet") or {})
    root_tests = dict(
        first_nonempty(
            runtime_truth_snapshot.get("root_tests"),
            runtime_truth_snapshot.get("verification"),
            {},
        )
        or {}
    )
    service = dict(runtime_truth_snapshot.get("service") or {})
    launch = dict(runtime_truth_snapshot.get("launch") or {})

    selected_best = str(selected_package.get("selected_best_profile_name") or "").strip()
    selected_active = str(selected_package.get("selected_active_profile_name") or "").strip()
    selected_confidence = str(selected_package.get("selected_package_confidence_label") or "").strip().lower()
    selected_deploy_recommendation = str(
        selected_package.get("selected_deploy_recommendation") or ""
    ).strip().lower()
    validation_live_filled_rows = int_or_none(selected_package.get("validation_live_filled_rows")) or 0
    generalization_ratio = _float_or_none(selected_package.get("generalization_ratio")) or 0.0
    launch_blocked_checks = {
        str(item).strip()
        for item in list(launch.get("blocked_checks") or [])
        if str(item).strip()
    }
    advisory_restart_checks = {"no_closed_trades", "finance_gate_blocked"}
    eligible = bool(
        root_tests.get("status") == "passing"
        and service.get("status") == "running"
        and selected_best
        and selected_active
        and selected_best != selected_active
        and selected_confidence in {"high", "medium"}
        and selected_deploy_recommendation in {"promote", "shadow_only"}
        and validation_live_filled_rows >= 12
        and generalization_ratio >= 0.80
        and _float_or_none(deployment_confidence.get("overall_score")) is not None
        and (_float_or_none(deployment_confidence.get("overall_score")) or 0.0) >= 0.45
        and _float_or_none(capital.get("deployed_capital_usd")) is not None
        and (_float_or_none(capital.get("deployed_capital_usd")) or 0.0) > 0.0
        and _float_or_none(wallet.get("free_collateral_usd")) is not None
        and (_float_or_none(wallet.get("free_collateral_usd")) or 0.0) > 0.0
        and launch_blocked_checks.issubset(advisory_restart_checks)
    )
    return {
        "eligible": eligible,
        "selected_best_profile_name": selected_best or None,
        "selected_active_profile_name": selected_active or None,
        "selected_deploy_recommendation": selected_deploy_recommendation or None,
        "selected_package_confidence_label": selected_confidence or None,
        "validation_live_filled_rows": validation_live_filled_rows,
        "generalization_ratio": round(generalization_ratio, 4),
        "advisory_restart_checks": sorted(advisory_restart_checks),
        "launch_blocked_checks": sorted(launch_blocked_checks),
        "reason_codes": (
            [
                "frontier_winner_differs_from_live",
                "high_confidence_shadow_or_promote_candidate",
                "sufficient_validation_rows",
                "bounded_stage1_restart_allowed_without_new_spend",
            ]
            if eligible
            else []
        ),
    }


def build_canonical_launch_packet(
    *,
    root: Path,
    runtime_truth_snapshot: dict[str, Any],
    launch_checklist_path: Path,
) -> dict[str, Any]:
    launch = dict(runtime_truth_snapshot.get("launch") or {})
    deployment_confidence = dict(runtime_truth_snapshot.get("deployment_confidence") or {})
    state_improvement = dict(runtime_truth_snapshot.get("state_improvement") or {})
    strategy = dict(state_improvement.get("strategy_recommendations") or {})
    scoreboard = dict(strategy.get("public_performance_scoreboard") or {})
    truth_lattice = dict(strategy.get("truth_lattice") or {})
    forecast_confidence = dict(strategy.get("btc5_forecast_confidence") or {})
    improvement_velocity = dict(state_improvement.get("improvement_velocity") or {})
    improvement_deltas = dict(improvement_velocity.get("deltas") or {})
    launch_state = _build_launch_state_bundle(runtime_truth_snapshot)

    contract = {
        "service_state": (launch_state.get("service") or {}).get("state") or "unknown",
        "agent_run_mode": runtime_truth_snapshot.get("agent_run_mode") or "unknown",
        "execution_mode": runtime_truth_snapshot.get("execution_mode") or "unknown",
        "paper_trading": runtime_truth_snapshot.get("paper_trading"),
        "allow_order_submission": runtime_truth_snapshot.get("allow_order_submission"),
        "order_submit_enabled": runtime_truth_snapshot.get("order_submit_enabled"),
        "launch_posture": runtime_truth_snapshot.get("launch_posture") or launch.get("posture") or "unknown",
    }
    contract_checks = _build_launch_contract_checks(contract=contract)
    failed_contract_checks = [item for item in contract_checks if not item.get("pass")]
    drift_kill_reasons = [f"{item['code']}: {item['detail']}" for item in failed_contract_checks]
    drift_kill_triggered = bool(failed_contract_checks)

    candidate_delta_arr_pct = _float_or_none(
        first_nonempty(
            scoreboard.get("forecast_arr_delta_pct"),
            scoreboard.get("timebound_velocity_forecast_gain_pct"),
            forecast_confidence.get("median_arr_delta_pct"),
        )
    )
    candidate_delta_arr_bps = (
        round(float(candidate_delta_arr_pct) * 100.0, 2)
        if candidate_delta_arr_pct is not None
        else 0.0
    )

    expected_improvement_velocity_delta = _float_or_none(
        first_nonempty(
            improvement_deltas.get("candidate_to_trade_conversion_delta"),
            improvement_deltas.get("edge_reachability_delta"),
            improvement_deltas.get("realized_expected_pnl_drift_delta_usd"),
            0.0,
        )
    )
    if expected_improvement_velocity_delta is None:
        expected_improvement_velocity_delta = 0.0

    arr_confidence_score = _float_or_none(deployment_confidence.get("overall_score"))
    if arr_confidence_score is None:
        arr_confidence_score = _confidence_label_to_score(
            str(
                first_nonempty(
                    deployment_confidence.get("confidence_label"),
                    forecast_confidence.get("confidence_label"),
                    "unknown",
                )
            )
        )

    finance_gate = load_finance_gate_status(root)
    finance_gate_pass = bool(finance_gate.get("finance_gate_pass"))
    treasury_gate_pass = bool(finance_gate.get("treasury_gate_pass", finance_gate_pass))
    bounded_stage1_restart = _bounded_stage1_restart_context(runtime_truth_snapshot)

    block_reasons = dedupe_preserve_order(
        [
            *[str(item) for item in list(launch.get("blocked_reasons") or []) if str(item).strip()],
            *[str(item) for item in list(launch.get("blocked_checks") or []) if str(item).strip()],
            *drift_kill_reasons,
            *[
                str(item)
                for item in list(truth_lattice.get("broken_reasons") or [])
                if str(item).strip()
            ],
            (
                f"finance_gate_blocked:{finance_gate.get('reason')}"
                if not finance_gate_pass and finance_gate.get("reason")
                else ""
            ),
        ]
    )
    block_reasons = [reason for reason in block_reasons if reason]
    if finance_gate_pass and finance_gate.get("capital_expansion_only_hold"):
        block_reasons = [
            reason
            for reason in block_reasons
            if not str(reason).startswith("finance_gate_blocked:")
        ]
    if bounded_stage1_restart.get("eligible"):
        block_reasons = [
            reason
            for reason in block_reasons
            if str(reason) not in {"no_closed_trades", "finance_gate_blocked"}
            and not str(reason).startswith("finance_gate_blocked:")
        ]

    live_launch_blocked = bool(launch.get("live_launch_blocked"))
    truth_lattice_broken = bool(truth_lattice.get("repair_branch_required"))
    if bounded_stage1_restart.get("eligible") and finance_gate_pass:
        live_launch_blocked = False
    canonical_blocked = bool(
        live_launch_blocked or drift_kill_triggered or truth_lattice_broken or not finance_gate_pass
    )
    launch_posture = "blocked" if canonical_blocked else "clear"
    allow_execution = not canonical_blocked

    one_next_cycle_action = str(launch.get("next_operator_action") or "").strip()
    if drift_kill_triggered:
        one_next_cycle_action = (
            "Repair launch-contract mismatches in service/mode/posture/order-submission fields, "
            "rerun `python3 scripts/write_remote_cycle_status.py`, then retry when launch_posture=clear."
        )
    elif truth_lattice_broken:
        one_next_cycle_action = str(
            truth_lattice.get("one_next_cycle_action")
            or "Repair truth-lattice contradictions and rerun the cycle packet before promoting any lane."
        ).strip()
    elif not finance_gate_pass:
        remediation = str(finance_gate.get("remediation") or "").strip()
        retry_at = str(finance_gate.get("retry_at") or "").strip()
        if remediation and retry_at:
            one_next_cycle_action = f"{remediation} Retry at {retry_at}."
        elif remediation:
            one_next_cycle_action = remediation
        elif finance_gate.get("reason"):
            one_next_cycle_action = (
                f"Resolve finance gate hold ({finance_gate['reason']}) and retry next cycle."
            )
        else:
            one_next_cycle_action = "Resolve finance policy hold and retry next cycle."
    elif bounded_stage1_restart.get("eligible"):
        one_next_cycle_action = (
            "Load the selected BTC5 frontier winner into the live stage-1 runtime, keep size flat, "
            "and refresh the cycle packet after the first fresh fills."
        )
    elif not one_next_cycle_action:
        one_next_cycle_action = "Run the next cycle with the current champion lane and publish refreshed packet artifacts."

    mandatory_outputs = {
        "candidate_delta_arr_bps": candidate_delta_arr_bps,
        "expected_improvement_velocity_delta": expected_improvement_velocity_delta,
        "arr_confidence_score": arr_confidence_score,
        "block_reasons": block_reasons,
        "finance_gate_pass": finance_gate_pass,
        "treasury_gate_pass": treasury_gate_pass,
        "one_next_cycle_action": one_next_cycle_action,
    }

    blocker_categories = build_blocker_category_map(block_reasons)

    return {
        "artifact": "launch_packet",
        "schema_version": 1,
        "generated_at": runtime_truth_snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "launch_verdict": {
            "posture": launch_posture,
            "allow_execution": allow_execution,
            "drift_kill_gate_triggered": drift_kill_triggered,
            "live_launch_blocked": canonical_blocked,
            "reason": (
                "blocked_by_drift_kill_gate"
                if drift_kill_triggered
                else (
                    "blocked_by_truth_lattice"
                    if truth_lattice_broken
                    else ("blocked_by_finance_gate" if not finance_gate_pass else "blocked_by_launch_checks")
                )
                if canonical_blocked
                else ("clear_bounded_stage1_restart" if bounded_stage1_restart.get("eligible") else "clear")
            ),
        },
        "contract": {
            **contract,
            "checks": contract_checks,
            "failed_checks": [item["code"] for item in failed_contract_checks],
        },
        "drift_kill_gate": {
            "triggered": drift_kill_triggered,
            "reasons": drift_kill_reasons,
        },
        "launch_state": launch_state,
        "blocker_categories": blocker_categories,
        "finance_gate": {
            "pass": finance_gate_pass,
            "treasury_pass": treasury_gate_pass,
            "reason": finance_gate.get("reason"),
            "treasury_reason": finance_gate.get("treasury_reason"),
            "remediation": finance_gate.get("remediation"),
            "retry_at": finance_gate.get("retry_at"),
            "retry_in_minutes": finance_gate.get("retry_in_minutes"),
            "requested_mode": finance_gate.get("requested_mode"),
            "finance_state": finance_gate.get("finance_state"),
            "stage_cap": finance_gate.get("stage_cap"),
            "capital_expansion_only_hold": finance_gate.get("capital_expansion_only_hold"),
            "source": finance_gate.get("source"),
        },
        "bounded_stage1_restart": bounded_stage1_restart,
        "mandatory_outputs": mandatory_outputs,
        "sources": {
            "runtime_truth_latest_json": (runtime_truth_snapshot.get("artifacts") or {}).get(
                "runtime_truth_latest_json"
            ),
            "remote_cycle_status_json": (runtime_truth_snapshot.get("artifacts") or {}).get(
                "remote_cycle_status_json"
            ),
            "remote_service_status_json": (runtime_truth_snapshot.get("artifacts") or {}).get(
                "remote_service_status_json"
            ),
            "trading_launch_checklist": relative_path_text(root, root / launch_checklist_path),
        },
    }
