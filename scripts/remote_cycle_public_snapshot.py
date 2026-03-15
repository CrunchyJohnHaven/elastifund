from __future__ import annotations

from typing import Any


def _derive_selection_compat_fields(runtime_truth_snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_package = dict(runtime_truth_snapshot.get("btc5_selected_package") or {})
    selected_best_profile = str(
        runtime_truth_snapshot.get("selected_best_profile")
        or selected_package.get("selected_best_profile_name")
        or selected_package.get("selected_active_profile_name")
        or runtime_truth_snapshot.get("selected_policy_id")
        or ""
    ).strip() or None
    selected_policy_id = str(
        runtime_truth_snapshot.get("selected_policy_id")
        or selected_package.get("selected_policy_id")
        or selected_best_profile
        or ""
    ).strip() or None
    selected_best_runtime_package = (
        runtime_truth_snapshot.get("selected_best_runtime_package")
        if isinstance(runtime_truth_snapshot.get("selected_best_runtime_package"), dict)
        else (
            selected_package.get("selected_best_runtime_package")
            if isinstance(selected_package.get("selected_best_runtime_package"), dict)
            else None
        )
    )
    promotion_state = str(
        runtime_truth_snapshot.get("promotion_state")
        or selected_package.get("promotion_state")
        or ("live_promoted" if selected_package.get("promoted_package_selected") else "")
    ).strip().lower() or None
    return {
        "selected_best_profile": selected_best_profile,
        "selected_policy_id": selected_policy_id,
        "selected_best_runtime_package": selected_best_runtime_package,
        "promotion_state": promotion_state,
        "selected_runtime_package_freshness": selected_package.get("freshness"),
        "selected_runtime_package_generated_at": selected_package.get("generated_at"),
    }


def build_public_headlines(
    *,
    launch: dict[str, Any],
    wallet_flow: dict[str, Any],
    service: dict[str, Any],
    verification: dict[str, Any],
    drift: dict[str, Any],
) -> list[str]:
    headlines: list[str] = []
    if drift.get("service_running_while_launch_blocked"):
        headlines.append(
            "jj-live.service is running while launch posture remains blocked; treat this as drift until the remote mode is reconciled."
        )
    if wallet_flow.get("ready"):
        headlines.append("Wallet-flow bootstrap is ready.")
    else:
        headlines.append(
            "Wallet-flow bootstrap is not ready: "
            + ", ".join(wallet_flow.get("reasons") or ["unknown"])
        )
    headlines.append(
        f"Latest root verification status is {verification['status']} ({verification['summary']})."
    )
    if launch.get("live_launch_blocked"):
        headlines.append("Launch posture remains blocked.")
    elif service.get("status") == "running":
        headlines.append("Runtime is unblocked and the service is running.")
    return headlines


def build_public_runtime_snapshot(runtime_truth_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build a sanitized snapshot for docs and the website."""

    capital = runtime_truth_snapshot["capital"]
    runtime = runtime_truth_snapshot["runtime"]
    launch = runtime_truth_snapshot["launch"]
    wallet_flow = runtime_truth_snapshot["wallet_flow"]
    polymarket_wallet = runtime_truth_snapshot.get("polymarket_wallet") or {}
    btc5_maker = runtime_truth_snapshot.get("btc_5min_maker") or {}
    service = runtime_truth_snapshot["service"]
    verification = runtime_truth_snapshot["verification"]
    structural_gates = runtime_truth_snapshot["structural_gates"]
    latest_edge_scan = runtime_truth_snapshot["latest_edge_scan"]
    latest_pipeline = runtime_truth_snapshot["latest_pipeline"]
    state_improvement = runtime_truth_snapshot.get("state_improvement") or {}
    drift = runtime_truth_snapshot["drift"]
    btc5_stage_readiness = runtime_truth_snapshot.get("btc5_stage_readiness") or {}
    deployment_confidence = runtime_truth_snapshot.get("deployment_confidence") or {}
    source_precedence = runtime_truth_snapshot.get("source_precedence") or {}
    truth_precedence = runtime_truth_snapshot.get("truth_precedence") or state_improvement.get("truth_precedence") or {}
    truth_lattice = runtime_truth_snapshot.get("truth_lattice") or (
        (state_improvement.get("strategy_recommendations") or {}).get("truth_lattice")
        or {}
    )
    launch_packet = runtime_truth_snapshot.get("launch_packet") or {}
    selection_compat = _derive_selection_compat_fields(runtime_truth_snapshot)

    return {
        "artifact": "public_runtime_snapshot",
        "schema_version": 1,
        "generated_at": runtime_truth_snapshot["generated_at"],
        "snapshot_source": runtime_truth_snapshot["artifacts"]["runtime_truth_latest_json"],
        "launch_posture": (launch_packet.get("launch_verdict") or {}).get("posture")
        or launch.get("posture"),
        "live_launch_blocked": (launch_packet.get("launch_verdict") or {}).get(
            "live_launch_blocked"
        ),
        "service_state": runtime_truth_snapshot.get("service_state") or service.get("status"),
        "one_next_cycle_action": (launch_packet.get("mandatory_outputs") or {}).get(
            "one_next_cycle_action"
        )
        or launch.get("next_operator_action"),
        "selected_best_profile": selection_compat.get("selected_best_profile"),
        "selected_policy_id": selection_compat.get("selected_policy_id"),
        "selected_best_runtime_package": selection_compat.get("selected_best_runtime_package"),
        "promotion_state": selection_compat.get("promotion_state"),
        "selected_runtime_package_freshness": selection_compat.get(
            "selected_runtime_package_freshness"
        ),
        "selected_runtime_package_generated_at": selection_compat.get(
            "selected_runtime_package_generated_at"
        ),
        "launch_state": dict(
            launch_packet.get("launch_state")
            or runtime_truth_snapshot.get("launch_state")
            or {}
        ),
        "capital": {
            "tracked_capital_usd": capital["tracked_capital_usd"],
            "deployed_capital_usd": capital["deployed_capital_usd"],
            "undeployed_capital_usd": capital["undeployed_capital_usd"],
            "bankroll_usd": runtime["bankroll_usd"],
            "polymarket_actual_deployable_usd": capital.get("polymarket_actual_deployable_usd"),
            "polymarket_observed_total_usd": capital.get("polymarket_observed_total_usd"),
            "polymarket_tracked_vs_observed_delta_usd": capital.get(
                "polymarket_tracked_vs_observed_delta_usd"
            ),
        },
        "runtime": {
            "cycles_completed": runtime["cycles_completed"],
            "total_trades": runtime["total_trades"],
            "total_trades_source": runtime.get("total_trades_source"),
            "total_trades_observations": runtime.get("total_trades_observations") or {},
            "closed_trades": runtime["closed_trades"],
            "open_positions": runtime["open_positions"],
            "daily_pnl_usd": runtime["daily_pnl_usd"],
            "total_pnl_usd": runtime["total_pnl_usd"],
            "polymarket_open_positions": runtime.get("polymarket_open_positions"),
            "polymarket_live_orders": runtime.get("polymarket_live_orders"),
            "polymarket_closed_positions_realized_pnl_usd": runtime.get(
                "polymarket_closed_positions_realized_pnl_usd"
            ),
            "btc5_source": runtime.get("btc5_source"),
            "btc5_db_path": runtime.get("btc5_db_path"),
            "btc5_live_filled_rows": runtime.get("btc5_live_filled_rows"),
            "btc5_live_filled_pnl_usd": runtime.get("btc5_live_filled_pnl_usd"),
            "btc5_latest_order_status": runtime.get("btc5_latest_order_status"),
            "btc5_intraday_live_summary": runtime.get("btc5_intraday_live_summary") or {},
        },
        "runtime_mode": {
            "remote_runtime_profile": runtime_truth_snapshot.get("remote_runtime_profile"),
            "agent_run_mode": runtime_truth_snapshot.get("agent_run_mode"),
            "execution_mode": runtime_truth_snapshot.get("execution_mode"),
            "paper_trading": runtime_truth_snapshot.get("paper_trading"),
            "allow_order_submission": runtime_truth_snapshot.get("allow_order_submission"),
            "order_submit_enabled": runtime_truth_snapshot.get("order_submit_enabled"),
        },
        "service": {
            "status": service["status"],
            "checked_at": service.get("checked_at"),
            "drift_detected": service.get("drift_detected", False),
            "drift_reason": service.get("drift_reason"),
        },
        "launch": {
            "posture": launch["posture"],
            "fast_flow_restart_ready": launch["fast_flow_restart_ready"],
            "live_launch_blocked": launch["live_launch_blocked"],
            "blocked_reasons": list(launch.get("blocked_reasons") or []),
            "next_operator_action": launch["next_operator_action"],
        },
        "launch_packet": {
            "posture": (launch_packet.get("launch_verdict") or {}).get("posture"),
            "allow_execution": (launch_packet.get("launch_verdict") or {}).get("allow_execution"),
            "drift_kill_gate_triggered": (launch_packet.get("launch_verdict") or {}).get(
                "drift_kill_gate_triggered"
            ),
            "launch_state": dict(launch_packet.get("launch_state") or {}),
            "mandatory_outputs": dict(launch_packet.get("mandatory_outputs") or {}),
        },
        "btc5_stage_readiness": {
            "can_trade_now": btc5_stage_readiness.get("can_trade_now"),
            "baseline_live_allowed": btc5_stage_readiness.get("baseline_live_allowed"),
            "baseline_live_blocking_checks": list(
                btc5_stage_readiness.get("baseline_live_blocking_checks") or []
            ),
            "stage_upgrade_can_trade_now": btc5_stage_readiness.get("stage_upgrade_can_trade_now"),
            "stage_upgrade_blocking_checks": list(
                btc5_stage_readiness.get("stage_upgrade_trade_now_blocking_checks") or []
            ),
            "allowed_stage": deployment_confidence.get("allowed_stage"),
            "allowed_stage_label": deployment_confidence.get("allowed_stage_label"),
            "stage_1_blockers": list(deployment_confidence.get("stage_1_blockers") or []),
            "stage_2_blockers": list(deployment_confidence.get("stage_2_blockers") or []),
            "stage_3_blockers": list(deployment_confidence.get("stage_3_blockers") or []),
            "raw_stage_readiness_stage_2_blockers": list(
                btc5_stage_readiness.get("stage_2_blockers") or []
            ),
            "raw_stage_readiness_stage_3_blockers": list(
                btc5_stage_readiness.get("stage_3_blockers") or []
            ),
            "freshness": btc5_stage_readiness.get("freshness"),
            "probe_freshness_hours": btc5_stage_readiness.get("probe_freshness_hours"),
        },
        "deployment_confidence": {
            "confidence_label": deployment_confidence.get("confidence_label"),
            "freshness_score": deployment_confidence.get("freshness_score"),
            "accounting_coherence_score": deployment_confidence.get("accounting_coherence_score"),
            "stage_readiness_score": deployment_confidence.get("stage_readiness_score"),
            "confirmation_coverage_score": deployment_confidence.get("confirmation_coverage_score"),
            "confirmation_evidence_score": deployment_confidence.get("confirmation_evidence_score"),
            "confirmation_coverage_label": deployment_confidence.get("confirmation_coverage_label"),
            "confirmation_strength_label": deployment_confidence.get("confirmation_strength_label"),
            "confirmation_strength_score": deployment_confidence.get("confirmation_strength_score"),
            "confirmation_freshness_label": deployment_confidence.get("confirmation_freshness_label"),
            "best_confirmation_source": deployment_confidence.get("best_confirmation_source"),
            "can_btc5_trade_now": deployment_confidence.get("can_btc5_trade_now"),
            "baseline_live_allowed": deployment_confidence.get("baseline_live_allowed"),
            "baseline_live_blocking_checks": list(
                deployment_confidence.get("baseline_live_blocking_checks") or []
            ),
            "stage_upgrade_can_trade_now": deployment_confidence.get("stage_upgrade_can_trade_now"),
            "allowed_stage": deployment_confidence.get("allowed_stage"),
            "allowed_stage_label": deployment_confidence.get("allowed_stage_label"),
            "blocking_checks": list(deployment_confidence.get("blocking_checks") or []),
            "next_required_artifact": deployment_confidence.get("next_required_artifact"),
        },
        "truth_gate_status": runtime_truth_snapshot.get("truth_gate_status"),
        "truth_gate_blocking_checks": list(
            runtime_truth_snapshot.get("truth_gate_blocking_checks") or []
        ),
        "truth_lattice": truth_lattice,
        "truth_precedence": truth_precedence,
        "source_precedence": {
            "rule": source_precedence.get("rule"),
            "fields": list(source_precedence.get("fields") or []),
            "contradictions": list(source_precedence.get("contradictions") or []),
        },
        "wallet_flow": {
            "status": wallet_flow["status"],
            "ready": wallet_flow["ready"],
            "wallet_count": wallet_flow["wallet_count"],
            "last_updated": wallet_flow.get("last_updated"),
        },
        "polymarket_wallet": {
            "status": polymarket_wallet.get("status"),
            "checked_at": polymarket_wallet.get("checked_at"),
            "free_collateral_usd": polymarket_wallet.get("free_collateral_usd"),
            "reserved_order_usd": polymarket_wallet.get("reserved_order_usd"),
            "live_orders_count": polymarket_wallet.get("live_orders_count"),
            "open_positions_count": polymarket_wallet.get("open_positions_count"),
            "positions_current_value_usd": polymarket_wallet.get("positions_current_value_usd"),
            "positions_unrealized_pnl_usd": polymarket_wallet.get(
                "positions_unrealized_pnl_usd"
            ),
            "closed_positions_realized_pnl_usd": polymarket_wallet.get(
                "closed_positions_realized_pnl_usd"
            ),
            "total_wallet_value_usd": polymarket_wallet.get("total_wallet_value_usd"),
            "warnings": list(polymarket_wallet.get("warnings") or []),
        },
        "btc_5min_maker": {
            "status": btc5_maker.get("status"),
            "checked_at": btc5_maker.get("checked_at"),
            "source": btc5_maker.get("source"),
            "db_path": btc5_maker.get("db_path"),
            "live_filled_rows": btc5_maker.get("live_filled_rows"),
            "live_filled_pnl_usd": btc5_maker.get("live_filled_pnl_usd"),
            "estimated_maker_rebate_usd": btc5_maker.get("estimated_maker_rebate_usd"),
            "net_pnl_after_estimated_rebate_usd": btc5_maker.get("net_pnl_after_estimated_rebate_usd"),
            "avg_live_filled_pnl_usd": btc5_maker.get("avg_live_filled_pnl_usd"),
            "avg_estimated_maker_rebate_usd": btc5_maker.get("avg_estimated_maker_rebate_usd"),
            "avg_net_pnl_after_estimated_rebate_usd": btc5_maker.get(
                "avg_net_pnl_after_estimated_rebate_usd"
            ),
            "latest_live_filled_at": btc5_maker.get("latest_live_filled_at"),
            "latest_trade": btc5_maker.get("latest_trade") or {},
            "recent_live_filled": list(btc5_maker.get("recent_live_filled") or []),
            "fill_attribution": btc5_maker.get("fill_attribution") or {},
            "intraday_live_summary": btc5_maker.get("intraday_live_summary") or {},
        },
        "structural_gates": {
            "a6": {
                "status": structural_gates["a6"]["status"],
                "summary": structural_gates["a6"]["summary"],
            },
            "b1": {
                "status": structural_gates["b1"]["status"],
                "summary": structural_gates["b1"]["summary"],
            },
        },
        "verification": {
            "status": verification["status"],
            "summary": verification["summary"],
            "checked_at": verification.get("checked_at"),
        },
        "latest_edge_scan": {
            "path": latest_edge_scan.get("path"),
            "generated_at": latest_edge_scan.get("generated_at"),
            "recommended_action": latest_edge_scan.get("recommended_action"),
            "action_reason": latest_edge_scan.get("action_reason"),
        },
        "latest_pipeline": {
            "path": latest_pipeline.get("path"),
            "report_generated_at": latest_pipeline.get("report_generated_at"),
            "recommendation": latest_pipeline.get("recommendation"),
            "reasoning": latest_pipeline.get("reasoning"),
        },
        "state_improvement": {
            "operator_digest": state_improvement.get("operator_digest"),
            "hourly_budget_progress": state_improvement.get("hourly_budget_progress"),
            "active_thresholds": state_improvement.get("active_thresholds"),
            "per_venue_candidate_counts": state_improvement.get("per_venue_candidate_counts"),
            "per_venue_executed_notional_usd": (
                state_improvement.get("per_venue_executed_notional_usd") or {}
            ),
            "per_venue_trade_counts": (
                state_improvement.get("per_venue_trade_counts") or {}
            ),
            "reject_reasons": state_improvement.get("reject_reasons") or [],
            "improvement_velocity": state_improvement.get("improvement_velocity") or {},
            "five_metric_scorecard": state_improvement.get("five_metric_scorecard") or {},
            "strategy_recommendations": state_improvement.get("strategy_recommendations") or {},
        },
        "operator_headlines": build_public_headlines(
            launch=launch,
            wallet_flow=wallet_flow,
            service=service,
            verification=verification,
            drift=drift,
        ),
    }
