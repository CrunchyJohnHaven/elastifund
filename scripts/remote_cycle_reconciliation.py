from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.remote_cycle_common import dedupe_preserve_order, relative_path_text


def _parse_datetime_like(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _remove_items(items: list[Any], blocked: set[str]) -> list[str]:
    return [
        str(item).strip()
        for item in items
        if str(item).strip() and str(item).strip() not in blocked
    ]


def _reconcile_btc5_baseline_live(snapshot: dict[str, Any], launch_packet: dict[str, Any]) -> None:
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    contract = dict(launch_packet.get("contract") or {})
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    launch_state = dict(snapshot.get("launch_state") or launch_packet.get("launch_state") or {})
    stage_state = dict(launch_state.get("stage") or {})
    btc5_stage_readiness = dict(snapshot.get("btc5_stage_readiness") or {})
    deployment_confidence = dict(snapshot.get("deployment_confidence") or {})
    accounting_reconciliation = dict(snapshot.get("accounting_reconciliation") or {})
    service = dict(snapshot.get("service") or {})
    state_improvement = dict(snapshot.get("state_improvement") or {})
    strategy = dict(state_improvement.get("strategy_recommendations") or {})
    champion = dict(strategy.get("champion_lane_contract") or {})
    blocker_classes = dict(champion.get("blocker_classes") or {})
    required_outputs = dict(champion.get("required_outputs") or {})
    candidate_recovery = dict(strategy.get("btc5_candidate_recovery") or {})

    finance_gate_pass = bool(mandatory_outputs.get("finance_gate_pass", True))
    launch_posture = str(launch_verdict.get("posture") or snapshot.get("launch_posture") or "blocked").strip().lower()
    service_state = str(
        contract.get("service_state")
        or snapshot.get("service_state")
        or service.get("status")
        or "unknown"
    ).strip().lower()
    execution_mode = str(
        contract.get("execution_mode")
        or snapshot.get("execution_mode")
        or "unknown"
    ).strip().lower()
    paper_trading = _bool_or_none(
        contract.get("paper_trading")
        if contract.get("paper_trading") is not None
        else snapshot.get("paper_trading")
    )
    allow_order_submission = bool(
        contract.get("allow_order_submission")
        if contract.get("allow_order_submission") is not None
        else snapshot.get("allow_order_submission")
    )
    order_submit_enabled = bool(
        contract.get("order_submit_enabled")
        if contract.get("order_submit_enabled") is not None
        else snapshot.get("order_submit_enabled")
    )

    baseline_live_blockers: list[str] = []
    if launch_posture != "clear":
        baseline_live_blockers.append(f"launch_posture_not_clear:{launch_posture or 'unknown'}")
    if service_state != "running":
        baseline_live_blockers.append(f"service_state_not_running:{service_state or 'unknown'}")
    if execution_mode != "live":
        baseline_live_blockers.append(f"execution_mode_not_live:{execution_mode or 'unknown'}")
    if paper_trading is True:
        baseline_live_blockers.append("paper_trading_enabled")
    if not allow_order_submission:
        baseline_live_blockers.append("allow_order_submission_false")
    if not order_submit_enabled:
        baseline_live_blockers.append("order_submit_enabled_false")
    if not finance_gate_pass:
        baseline_live_blockers.append("finance_gate_blocked")

    baseline_live_allowed = not baseline_live_blockers
    stage_upgrade_can_trade_now = bool(
        deployment_confidence.get("stage_upgrade_can_trade_now")
        if "stage_upgrade_can_trade_now" in deployment_confidence
        else deployment_confidence.get("can_btc5_trade_now")
    )
    stage_upgrade_trade_now_status = "unblocked" if stage_upgrade_can_trade_now else "blocked"
    stage_upgrade_trade_now_blocking_checks = list(
        btc5_stage_readiness.get("stage_upgrade_trade_now_blocking_checks")
        or btc5_stage_readiness.get("deployment_trade_now_blocking_checks")
        or deployment_confidence.get("stage_1_blockers")
        or btc5_stage_readiness.get("blocking_checks")
        or []
    )
    if not stage_upgrade_trade_now_blocking_checks and not stage_upgrade_can_trade_now:
        stage_upgrade_trade_now_blocking_checks = ["stage_upgrade_blocked_by_deployment_confidence"]
    stage_upgrade_trade_now_reasons = list(
        btc5_stage_readiness.get("stage_upgrade_trade_now_reasons")
        or btc5_stage_readiness.get("deployment_trade_now_reasons")
        or btc5_stage_readiness.get("trade_now_reasons")
        or []
    )
    if not stage_upgrade_trade_now_reasons:
        stage_upgrade_trade_now_reasons = (
            [
                "BTC5 stage-upgrade progression is blocked by deployment confidence checks."
            ]
            if not stage_upgrade_can_trade_now
            else [
                "BTC5 stage-upgrade progression is currently unblocked."
            ]
        )
    btc5_stage_readiness.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_status": "unblocked" if baseline_live_allowed else "blocked",
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "can_trade_now": baseline_live_allowed,
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_trade_now_status": stage_upgrade_trade_now_status,
            "stage_upgrade_trade_now_blocking_checks": list(stage_upgrade_trade_now_blocking_checks),
            "stage_upgrade_trade_now_reasons": list(stage_upgrade_trade_now_reasons),
            "trade_now_status": "unblocked" if baseline_live_allowed else "blocked",
            "trade_now_blocking_checks": list(baseline_live_blockers),
            "trade_now_reasons": (
                [
                    "BTC5 baseline live trading is permitted at flat stage-1 size while stage upgrades remain separately gated."
                ]
                if baseline_live_allowed
                else ["BTC5 baseline live trading is blocked by the launch/runtime/finance contract."]
            ),
        }
    )
    snapshot["btc5_stage_readiness"] = btc5_stage_readiness

    deployment_confidence.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_status": "unblocked" if baseline_live_allowed else "blocked",
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_trade_now_reasons": stage_upgrade_trade_now_reasons,
        }
    )
    snapshot["deployment_confidence"] = deployment_confidence

    stage_state.update(
        {
            "baseline_live_allowed": baseline_live_allowed,
            "baseline_live_blocking_checks": list(baseline_live_blockers),
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "stage_upgrade_blocking_checks": list(
                btc5_stage_readiness.get("stage_upgrade_trade_now_blocking_checks") or []
            ),
            "can_trade_now": baseline_live_allowed,
            "blocking_checks": list(baseline_live_blockers),
        }
    )
    launch_state["stage"] = stage_state
    snapshot["launch_state"] = launch_state
    launch_packet.setdefault("launch_state", {})["stage"] = stage_state

    snapshot["can_btc5_trade_now"] = baseline_live_allowed
    snapshot["btc5_baseline_live_allowed"] = baseline_live_allowed
    snapshot["btc5_stage_upgrade_can_trade_now"] = stage_upgrade_can_trade_now

    service_drift_reasons = {
        "Service-state drift: btc-5min-maker.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow.",
    }
    stale_truth_blockers = set()
    if not accounting_reconciliation.get("drift_detected"):
        stale_truth_blockers.add("accounting_reconciliation_drift")
    if launch_posture == "clear" and service_state == "running":
        stale_truth_blockers.update({"service_status_stale", "stale_service_file_with_fresh_btc5_probe"})

    drift_payload = dict(snapshot.get("drift") or {})
    drift_reasons = [
        reason
        for reason in list(drift_payload.get("reasons") or [])
        if reason not in service_drift_reasons
        and not reason.startswith("finance_gate_blocked:")
        and not reason.startswith("Accounting drift: ")
    ]
    if accounting_reconciliation.get("drift_detected"):
        drift_reasons.extend(
            [
                reason
                for reason in list(drift_payload.get("reasons") or [])
                if str(reason).startswith("Accounting drift: ")
            ]
        )
    if not finance_gate_pass:
        drift_reasons.extend(
            [
                reason
                for reason in list(drift_payload.get("reasons") or [])
                if str(reason).startswith("finance_gate_blocked:")
            ]
        )
    drift_payload.update(
        {
            "service_running_while_launch_blocked": launch_posture != "clear" and service_state == "running",
            "reasons": dedupe_preserve_order(drift_reasons),
        }
    )
    drift_payload["detected"] = bool(
        drift_payload.get("drift_kill_gate_triggered") or drift_payload.get("reasons")
    )
    snapshot["drift"] = drift_payload
    snapshot["drift_detected"] = bool(drift_payload["detected"])
    snapshot["service_drift_detected"] = bool(drift_payload["service_running_while_launch_blocked"])
    snapshot["accounting_drift_detected"] = bool(accounting_reconciliation.get("drift_detected"))

    service["drift_detected"] = bool(drift_payload["service_running_while_launch_blocked"])
    service["drift_reason"] = (
        "Service-state drift: btc-5min-maker.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow."
        if service["drift_detected"]
        else None
    )
    snapshot["service"] = service

    reconciliation = dict(snapshot.get("reconciliation") or {})
    if isinstance(reconciliation.get("service"), dict):
        reconciliation_service = dict(reconciliation.get("service") or {})
        reconciliation_service["drift_detected"] = service["drift_detected"]
        reconciliation_service["drift_reason"] = service["drift_reason"]
        reconciliation["service"] = reconciliation_service
    snapshot["reconciliation"] = reconciliation

    launch_payload = dict(snapshot.get("launch") or {})
    launch_payload["posture"] = launch_posture
    launch_payload["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    snapshot["launch"] = launch_payload

    summary = dict(snapshot.get("summary") or {})
    summary.update(
        {
            "btc5_can_trade_now": baseline_live_allowed,
            "btc5_baseline_live_allowed": baseline_live_allowed,
            "btc5_stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
            "drift_detected": bool(drift_payload["detected"]),
        }
    )

    retry_minutes = (
        int(champion.get("finance_gate", {}).get("retry_in_minutes") or 0) or 10
    )
    truth_bucket = dict(blocker_classes.get("truth") or {})
    truth_checks = _remove_items(list(truth_bucket.get("checks") or []), stale_truth_blockers)
    truth_bucket["checks"] = truth_checks
    truth_bucket["status"] = "blocked" if truth_checks else "clear"
    blocker_classes["truth"] = truth_bucket

    required_outputs["block_reasons"] = _remove_items(
        list(required_outputs.get("block_reasons") or []),
        stale_truth_blockers,
    )
    champion_lane = dict(champion.get("champion_lane") or {})
    champion_lane.update(
        {
            "can_trade_now": baseline_live_allowed,
            "baseline_live_allowed": baseline_live_allowed,
            "stage_upgrade_can_trade_now": stage_upgrade_can_trade_now,
        }
    )
    champion["champion_lane"] = champion_lane
    champion["blocker_classes"] = blocker_classes
    champion["required_outputs"] = required_outputs

    search_generated_at = _parse_datetime_like(candidate_recovery.get("generated_at"))
    search_stale = False
    if search_generated_at is not None:
        search_stale = (datetime.now(timezone.utc) - search_generated_at).total_seconds() > 6 * 3600

    if baseline_live_allowed and not truth_checks and finance_gate_pass:
        next_reason_source = (
            (blocker_classes.get("confirmation") or {}).get("checks")
            or (blocker_classes.get("candidate") or {}).get("checks")
            or ["stage_upgrade_blockers"]
        )
        champion["status"] = "candidate_ready"
        champion["decision_reason"] = (
            "btc5_baseline_live_allowed_stage_upgrade_blocked"
            if not stage_upgrade_can_trade_now
            else "btc5_is_the_only_tradeable_champion_lane"
        )
        reconciled_next_action = (
            f"Keep BTC5 baseline live at flat stage-1 size via {champion_lane.get('selected_profile_name') or 'active_profile'}; "
            f"repair {next_reason_source[0]} before any stage upgrade or capital expansion and rerun the cycle packet in +{retry_minutes}m."
            if not stage_upgrade_can_trade_now
            else champion["required_outputs"].get("one_next_cycle_action")
        )
        champion["required_outputs"]["one_next_cycle_action"] = reconciled_next_action
        launch_packet.setdefault("mandatory_outputs", {})["one_next_cycle_action"] = reconciled_next_action
        snapshot["one_next_cycle_action"] = reconciled_next_action
        if search_stale:
            champion.setdefault("notes", []).append(
                "fast_market_search_is_stale_do_not_let_old_search_blockers_override_the_live_baseline"
            )
    summary["trading_cycle_status"] = champion.get("status", summary.get("trading_cycle_status"))
    summary["one_next_cycle_action"] = snapshot.get("one_next_cycle_action", summary.get("one_next_cycle_action"))
    snapshot["summary"] = summary
    snapshot["champion_lane_contract"] = champion
    snapshot["trading_cycle_status"] = champion.get("status", snapshot.get("trading_cycle_status"))

    strategy["champion_lane_contract"] = champion
    state_improvement["strategy_recommendations"] = strategy
    state_improvement["decision_status"] = champion.get("status")
    state_improvement["one_next_cycle_action"] = summary.get("one_next_cycle_action")
    snapshot["state_improvement"] = state_improvement


def apply_canonical_launch_packet(
    runtime_truth_snapshot: dict[str, Any],
    *,
    root: Path,
    launch_packet: dict[str, Any],
    launch_packet_latest_path: Path,
    launch_packet_timestamped_path: Path,
) -> dict[str, Any]:
    snapshot = dict(runtime_truth_snapshot)
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    treasury_gate_pass = bool(
        mandatory_outputs.get(
            "treasury_gate_pass",
            mandatory_outputs.get("finance_gate_pass", True),
        )
    )
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    drift_gate = dict(launch_packet.get("drift_kill_gate") or {})
    contract = dict(launch_packet.get("contract") or {})
    checks = list(contract.get("checks") or [])
    expected_primary_service = "btc-5min-maker.service"
    observed_service_name = str((snapshot.get("service") or {}).get("service_name") or "").strip() or None
    mode_alignment_check = next(
        (
            item
            for item in checks
            if isinstance(item, dict) and str(item.get("code") or "").strip() == "mode_alignment"
        ),
        {},
    )
    mode_alignment_status = (
        "pass"
        if bool(mode_alignment_check.get("pass"))
        else ("fail" if mode_alignment_check else "unknown")
    )

    snapshot["launch_packet"] = launch_packet
    snapshot["launch_state"] = dict(launch_packet.get("launch_state") or {})
    snapshot["launch_posture"] = str(launch_verdict.get("posture") or snapshot.get("launch_posture") or "blocked")
    snapshot["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    snapshot["service_state"] = str(
        (launch_packet.get("contract") or {}).get("service_state")
        or snapshot.get("service_state")
        or "unknown"
    ).strip() or "unknown"
    launch_payload = dict(snapshot.get("launch") or {})
    launch_payload.update(
        {
            "posture": snapshot["launch_posture"],
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "blocked_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "blocked_checks": dedupe_preserve_order(
                [
                    *list(launch_payload.get("blocked_checks") or []),
                    *list((launch_packet.get("contract") or {}).get("failed_checks") or []),
                    "finance_gate_blocked" if not mandatory_outputs.get("finance_gate_pass", True) else "",
                ]
            ),
            "next_operator_action": mandatory_outputs.get("one_next_cycle_action"),
        }
    )
    launch_payload["blocked_checks"] = [item for item in launch_payload.get("blocked_checks") or [] if item]
    snapshot["launch"] = launch_payload

    snapshot.setdefault("summary", {}).update(
        {
            "launch_posture": snapshot["launch_posture"],
            "live_launch_blocked": snapshot["live_launch_blocked"],
            "one_next_cycle_action": mandatory_outputs.get("one_next_cycle_action"),
            "service_status": snapshot["service_state"],
            "storage_state": ((snapshot.get("launch_state") or {}).get("storage") or {}).get("state"),
            "package_load_state": ((snapshot.get("launch_state") or {}).get("package_load") or {}).get("state"),
            "btc5_allowed_stage": ((snapshot.get("launch_state") or {}).get("stage") or {}).get(
                "allowed_stage_label"
            ),
            "drift_detected": bool(
                snapshot.get("summary", {}).get("drift_detected")
                or snapshot.get("drift", {}).get("detected")
                or drift_gate.get("triggered")
            ),
        }
    )
    snapshot["block_reasons"] = list(mandatory_outputs.get("block_reasons") or [])
    snapshot["finance_gate_pass"] = bool(mandatory_outputs.get("finance_gate_pass"))
    snapshot["treasury_gate_pass"] = treasury_gate_pass
    snapshot["stage1_live_trading_allowed"] = bool(mandatory_outputs.get("finance_gate_pass"))
    snapshot["treasury_expansion_allowed"] = treasury_gate_pass
    snapshot["one_next_cycle_action"] = mandatory_outputs.get("one_next_cycle_action")
    snapshot["primary_service"] = expected_primary_service
    snapshot["expected_service_name"] = expected_primary_service
    snapshot["observed_service_name"] = observed_service_name
    snapshot["service_consistency"] = (
        "mismatch"
        if observed_service_name and observed_service_name != expected_primary_service
        else "consistent"
    )
    snapshot["mode_alignment"] = mode_alignment_status
    snapshot["runtime_contract"] = {
        "selected_runtime_profile": snapshot.get("selected_runtime_profile"),
        "effective_runtime_profile": snapshot.get("effective_runtime_profile"),
        "remote_runtime_profile": snapshot.get("remote_runtime_profile"),
        "agent_run_mode": snapshot.get("agent_run_mode"),
        "execution_mode": snapshot.get("execution_mode"),
        "paper_trading": snapshot.get("paper_trading"),
        "allow_order_submission": snapshot.get("allow_order_submission"),
        "primary_service": expected_primary_service,
        "observed_service_name": observed_service_name,
        "mode_alignment": mode_alignment_status,
    }

    drift_payload = dict(snapshot.get("drift") or {})
    drift_payload.update(
        {
            "detected": bool(drift_payload.get("detected") or drift_gate.get("triggered")),
            "drift_kill_gate_triggered": bool(drift_gate.get("triggered")),
            "reasons": dedupe_preserve_order(
                [
                    *list(drift_payload.get("reasons") or []),
                    *list(drift_gate.get("reasons") or []),
                    (
                        f"finance_gate_blocked:{(launch_packet.get('finance_gate') or {}).get('reason')}"
                        if not mandatory_outputs.get("finance_gate_pass", True)
                        and (launch_packet.get("finance_gate") or {}).get("reason")
                        else ""
                    ),
                ]
            ),
        }
    )
    drift_payload["reasons"] = [item for item in drift_payload.get("reasons") or [] if item]
    snapshot["drift"] = drift_payload
    _reconcile_btc5_baseline_live(snapshot, launch_packet)

    snapshot.setdefault("artifacts", {}).update(
        {
            "launch_packet_latest_json": relative_path_text(root, launch_packet_latest_path),
            "launch_packet_timestamped_json": relative_path_text(root, launch_packet_timestamped_path),
        }
    )
    return snapshot


def apply_canonical_launch_packet_to_status(
    status: dict[str, Any],
    *,
    launch_packet: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(status)
    mandatory_outputs = dict(launch_packet.get("mandatory_outputs") or {})
    treasury_gate_pass = bool(
        mandatory_outputs.get(
            "treasury_gate_pass",
            mandatory_outputs.get("finance_gate_pass", True),
        )
    )
    launch_verdict = dict(launch_packet.get("launch_verdict") or {})
    contract = dict(launch_packet.get("contract") or {})
    expected_primary_service = "btc-5min-maker.service"
    observed_service_name = str((payload.get("service") or {}).get("service_name") or "").strip() or None
    mode_alignment_check = next(
        (
            item
            for item in list(contract.get("checks") or [])
            if isinstance(item, dict) and str(item.get("code") or "").strip() == "mode_alignment"
        ),
        {},
    )
    mode_alignment_status = (
        "pass"
        if bool(mode_alignment_check.get("pass"))
        else ("fail" if mode_alignment_check else "unknown")
    )

    launch = dict(payload.get("launch") or {})
    launch.update(
        {
            "posture": launch_verdict.get("posture"),
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "blocked_reasons": list(mandatory_outputs.get("block_reasons") or []),
            "blocked_checks": dedupe_preserve_order(
                [
                    *list(launch.get("blocked_checks") or []),
                    *list((launch_packet.get("contract") or {}).get("failed_checks") or []),
                    "finance_gate_blocked" if not mandatory_outputs.get("finance_gate_pass", True) else "",
                ]
            ),
            "next_operator_action": mandatory_outputs.get("one_next_cycle_action"),
        }
    )
    launch["blocked_checks"] = [item for item in launch.get("blocked_checks") or [] if item]

    payload["launch"] = launch
    payload["launch_posture"] = launch_verdict.get("posture")
    payload["live_launch_blocked"] = bool(launch_verdict.get("live_launch_blocked"))
    payload["launch_state"] = dict(launch_packet.get("launch_state") or {})
    payload["service_state"] = str(
        (launch_packet.get("contract") or {}).get("service_state")
        or payload.get("service_state")
        or "unknown"
    ).strip() or "unknown"
    payload["launch_packet"] = launch_packet
    payload["finance_gate_pass"] = bool(mandatory_outputs.get("finance_gate_pass"))
    payload["treasury_gate_pass"] = treasury_gate_pass
    payload["stage1_live_trading_allowed"] = bool(mandatory_outputs.get("finance_gate_pass"))
    payload["treasury_expansion_allowed"] = treasury_gate_pass
    payload["one_next_cycle_action"] = mandatory_outputs.get("one_next_cycle_action")
    payload["block_reasons"] = list(mandatory_outputs.get("block_reasons") or [])
    payload["primary_service"] = expected_primary_service
    payload["expected_service_name"] = expected_primary_service
    payload["observed_service_name"] = observed_service_name
    payload["service_consistency"] = (
        "mismatch"
        if observed_service_name and observed_service_name != expected_primary_service
        else "consistent"
    )
    payload["mode_alignment"] = mode_alignment_status
    payload["runtime_contract"] = {
        "selected_runtime_profile": (payload.get("runtime_mode") or {}).get("selected_runtime_profile"),
        "effective_runtime_profile": (payload.get("runtime_mode") or {}).get("effective_runtime_profile"),
        "remote_runtime_profile": (payload.get("runtime_truth") or {}).get("remote_runtime_profile"),
        "agent_run_mode": (payload.get("runtime_truth") or {}).get("agent_run_mode"),
        "execution_mode": payload.get("execution_mode"),
        "paper_trading": payload.get("paper_trading"),
        "allow_order_submission": payload.get("allow_order_submission"),
        "primary_service": expected_primary_service,
        "observed_service_name": observed_service_name,
        "mode_alignment": mode_alignment_status,
    }
    payload.setdefault("runtime_truth", {}).update(
        {
            "launch_posture": launch_verdict.get("posture"),
            "live_launch_blocked": bool(launch_verdict.get("live_launch_blocked")),
            "launch_packet": launch_packet,
            "launch_state": dict(launch_packet.get("launch_state") or {}),
            "finance_gate_pass": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_gate_pass": treasury_gate_pass,
            "stage1_live_trading_allowed": bool(mandatory_outputs.get("finance_gate_pass")),
            "treasury_expansion_allowed": treasury_gate_pass,
            "one_next_cycle_action": mandatory_outputs.get("one_next_cycle_action"),
            "primary_service": expected_primary_service,
            "expected_service_name": expected_primary_service,
            "observed_service_name": observed_service_name,
            "service_consistency": (
                "mismatch"
                if observed_service_name and observed_service_name != expected_primary_service
                else "consistent"
            ),
            "mode_alignment": mode_alignment_status,
        }
    )
    runtime_truth = dict(payload.get("runtime_truth") or {})
    _reconcile_btc5_baseline_live(runtime_truth, launch_packet)
    payload["runtime_truth"] = runtime_truth
    payload["launch_state"] = dict(runtime_truth.get("launch_state") or payload.get("launch_state") or {})
    payload["btc5_stage_readiness"] = dict(runtime_truth.get("btc5_stage_readiness") or {})
    payload["deployment_confidence"] = dict(runtime_truth.get("deployment_confidence") or {})
    payload["can_btc5_trade_now"] = runtime_truth.get("can_btc5_trade_now")
    payload["btc5_baseline_live_allowed"] = runtime_truth.get("btc5_baseline_live_allowed")
    payload["btc5_stage_upgrade_can_trade_now"] = runtime_truth.get(
        "btc5_stage_upgrade_can_trade_now"
    )
    payload["launch"] = {
        **dict(payload.get("launch") or {}),
        **dict(runtime_truth.get("launch") or {}),
    }
    payload["service"] = {
        **dict(payload.get("service") or {}),
        **dict(runtime_truth.get("service") or {}),
    }
    payload["state_improvement"] = {
        **dict(payload.get("state_improvement") or {}),
        **dict(runtime_truth.get("state_improvement") or {}),
    }
    payload["truth_gate_status"] = runtime_truth.get("truth_gate_status") or payload.get(
        "truth_gate_status"
    )
    payload["truth_gate_blocking_checks"] = list(
        runtime_truth.get("truth_gate_blocking_checks") or payload.get("truth_gate_blocking_checks") or []
    )
    payload["truth_lattice"] = dict(runtime_truth.get("truth_lattice") or payload.get("truth_lattice") or {})
    payload["truth_precedence"] = dict(
        runtime_truth.get("truth_precedence") or payload.get("truth_precedence") or {}
    )
    payload["champion_lane_contract"] = dict(
        (
            ((runtime_truth.get("state_improvement") or {}).get("strategy_recommendations") or {}).get(
                "champion_lane_contract"
            )
        )
        or payload.get("champion_lane_contract")
        or {}
    )
    payload["one_next_cycle_action"] = runtime_truth.get("one_next_cycle_action") or payload.get(
        "one_next_cycle_action"
    )
    return payload
