from __future__ import annotations

import json
from typing import Any

from scripts.remote_cycle_common import format_money, safe_float


def render_runtime_mode_reconciliation_markdown(payload: dict[str, Any]) -> str:
    drift_flags = payload["drift_flags"]
    mode_reconciliation = payload["mode_reconciliation"]
    docs = mode_reconciliation["docs"]
    remote_probe = mode_reconciliation["remote_probe"]
    lines = [
        "# Runtime Mode Reconciliation",
        "",
        f"- Generated: {payload.get('generated_at') or 'unknown'}",
        f"- Service state: {payload['service_state']}",
        f"- Process state: {payload['process_state']}",
        f"- Remote runtime profile: {payload.get('remote_runtime_profile') or 'unknown'}",
        f"- Selected runtime profile: {payload.get('selected_runtime_profile') or 'unknown'}",
        f"- Effective runtime profile: {payload.get('effective_runtime_profile') or 'unknown'}",
        f"- Safe baseline profile: {payload.get('safe_baseline_profile') or 'unknown'}",
        f"- Safe baseline required: {'yes' if payload.get('safe_baseline_required') else 'no'}",
        f"- Agent run mode: {payload.get('agent_run_mode') or 'unknown'}",
        f"- Execution mode: {payload.get('execution_mode') or 'unknown'}",
        f"- Paper trading: {payload.get('paper_trading')}",
        f"- Allow order submission: {payload.get('allow_order_submission')}",
        f"- Order submit enabled: {'yes' if payload.get('order_submit_enabled') else 'no'}",
        f"- Launch posture: {payload['launch_posture']}",
        f"- Safe baseline profile: {payload.get('safe_baseline_profile') or 'unknown'}",
        f"- Safe baseline reason: {payload.get('safe_baseline_reason') or 'unknown'}",
        f"- Restart recommended: {'yes' if payload.get('restart_recommended') else 'no'}",
        "",
        "## Runtime Counts",
        "",
        f"- Cycles completed: {payload['cycles_completed']}",
        f"- Total trades: {payload['total_trades']}",
        f"- Open positions: {payload['open_positions']}",
        f"- Deployed capital: {format_money(payload['deployed_capital_usd'])}",
        "",
        "## Effective Caps",
        "",
    ]
    for key, value in payload["effective_caps"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Effective Thresholds",
            "",
        ]
    )
    for key, value in payload["effective_thresholds"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Drift Flags",
            "",
            f"- Count drift: {'yes' if drift_flags['count_drift'] else 'no'}",
            f"- Profile override drift: {'yes' if drift_flags['profile_override_drift'] else 'no'}",
            f"- Caps/threshold drift: {'yes' if drift_flags['caps_threshold_drift'] else 'no'}",
            f"- Docs stale: {'yes' if drift_flags['docs_stale'] else 'no'}",
            f"- Local/remote truth mismatch: {'yes' if drift_flags['local_remote_truth_mismatch'] else 'no'}",
            f"- Mode field ambiguity: {'yes' if drift_flags['mode_field_ambiguity'] else 'no'}",
            f"- Mode field inconsistency: {'yes' if drift_flags['mode_field_inconsistency'] else 'no'}",
            f"- Service running while launch blocked: {'yes' if drift_flags['service_running_while_launch_blocked'] else 'no'}",
            f"- Wallet balance drift: {'yes' if drift_flags.get('wallet_balance_drift') else 'no'}",
            "",
            "### Drift Reasons",
            "",
        ]
    )
    drift_reasons = drift_flags.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in drift_reasons)
    lines.extend(
        [
            "",
            "## Local / Remote / Docs",
            "",
            f"- Local selected profile: {mode_reconciliation['selected_profile']}",
            f"- Effective profile after guardrails: {mode_reconciliation.get('effective_profile') or 'unknown'}",
            f"- Local `.env` selector: {(mode_reconciliation['local_env'] or {}).get('JJ_RUNTIME_PROFILE') or 'unset'}",
            f"- Remote selector: {(mode_reconciliation['remote_mode']['values'] or {}).get('JJ_RUNTIME_PROFILE') or 'unknown'}",
            f"- Remote agent run mode: {(mode_reconciliation['remote_mode']['values'] or {}).get('ELASTIFUND_AGENT_RUN_MODE') or 'unknown'}",
            f"- Remote paper trading: {(mode_reconciliation['remote_mode']['values'] or {}).get('PAPER_TRADING') or 'unknown'}",
            f"- Remote status probe open positions: {remote_probe.get('open_positions', 'unknown')}",
            f"- Remote status probe last trades: {remote_probe.get('last_trades', 'unknown')}",
            "",
            "### Remote Probe Mismatches",
            "",
        ]
    )
    mismatches = [
        *list(mode_reconciliation["remote_probe_alignment"].get("feature_mismatches") or []),
        *list(mode_reconciliation["remote_probe_alignment"].get("count_mismatches") or []),
    ]
    lines.extend(f"- {item}" for item in (mismatches or ["none"]))
    lines.extend(
        [
            "",
            "### Docs Drift",
            "",
        ]
    )
    stale_references = docs.get("stale_references") or ["none"]
    if stale_references == ["none"]:
        lines.append("- none")
    else:
        for reference in stale_references:
            if isinstance(reference, str):
                lines.append(f"- {reference}")
                continue
            lines.append(
                f"- {reference['path']}:{reference['line']} -> {reference['excerpt']}"
            )
    lines.append("")
    return "\n".join(lines)


def _format_optional_float(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{safe_float(value):.4f}"


def _format_optional_pct(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{safe_float(value) * 100.0:.2f}%"


def render_remote_cycle_status_markdown(status: dict[str, Any]) -> str:
    """Render the remote-cycle status artifact in markdown."""

    capital = status["capital"]
    runtime = status["runtime"]
    flywheel = status["flywheel"]
    cadence = status["data_cadence"]
    forecast = status["velocity_forecast"]
    finish = status["deployment_finish"]
    service = status["service"]
    root_tests = status["root_tests"]
    wallet_flow = status["wallet_flow"]
    polymarket_wallet = status.get("polymarket_wallet") or {}
    btc5_maker = status.get("btc_5min_maker") or {}
    gates = status["structural_gates"]
    launch = status["launch"]
    truth = status["runtime_truth"]
    accounting_reconciliation = status.get("accounting_reconciliation") or {}
    btc5_stage_readiness = status.get("btc5_stage_readiness") or {}
    deployment_confidence = status.get("deployment_confidence") or {}
    source_precedence = status.get("source_precedence") or {}
    finance_gate = status.get("finance_gate") or {}
    champion_lane_contract = status.get("champion_lane_contract") or {}

    lines = [
        "# Remote Cycle Status",
        "",
        f"- Generated: {status['generated_at']}",
        f"- Service: {service['status']} ({service.get('systemctl_state') or 'unknown'})",
        f"- Root regression suite: {root_tests['status']}",
        f"- Wallet-flow bootstrap: {wallet_flow['status']}",
        f"- A-6 gate: {gates['a6']['status']}",
        f"- B-1 gate: {gates['b1']['status']}",
        f"- Runtime drift detected: {'yes' if truth['drift_detected'] else 'no'}",
        f"- Accounting reconciliation drift: {'yes' if accounting_reconciliation.get('drift_detected') else 'no'}",
        f"- BTC5 can trade now: {'yes' if deployment_confidence.get('can_btc5_trade_now') else 'no'}",
        f"- BTC5 allowed stage: {deployment_confidence.get('allowed_stage_label') or 'stage_0'}",
        f"- Deployment confidence: {deployment_confidence.get('confidence_label') or 'unknown'}",
        f"- Champion lane status: {champion_lane_contract.get('status') or 'unknown'}",
        f"- Challenger rule set: {(champion_lane_contract.get('challenger_rule_set') or {}).get('policy') or 'unknown'}",
        f"- Finance gate: {finance_gate.get('status') or 'unknown'}",
        f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
        f"- Next operator action: {launch['next_operator_action']}",
        "",
        "## Capital",
        "",
        "| Account | Tracked USD | Source |",
        "|---------|-------------|--------|",
    ]

    for item in capital["sources"]:
        lines.append(f"| {item['account']} | {format_money(item['amount_usd'])} | {item['source']} |")

    lines.extend(
        [
            "",
            f"- Total tracked capital: {format_money(capital['tracked_capital_usd'])}",
            f"- Capital currently deployed: {format_money(capital['deployed_capital_usd'])}",
            f"- Capital still undeployed: {format_money(capital['undeployed_capital_usd'])}",
            f"- Deployment progress: {capital['deployment_progress_pct']:.2f}%",
            (
                f"- Polymarket actual deployable USD: "
                f"{format_money(capital['polymarket_actual_deployable_usd'])}"
                if capital.get("polymarket_actual_deployable_usd") is not None
                else "- Polymarket actual deployable USD: n/a"
            ),
            (
                f"- Polymarket tracked vs observed delta: "
                f"{format_money(capital['polymarket_tracked_vs_observed_delta_usd'])}"
                if capital.get("polymarket_tracked_vs_observed_delta_usd") is not None
                else "- Polymarket tracked vs observed delta: n/a"
            ),
            "",
            "## Runtime",
            "",
            f"- Bankroll: {format_money(runtime['bankroll_usd'])}",
            f"- Daily PnL: {format_money(runtime['daily_pnl_usd'])} ({runtime.get('daily_pnl_date') or 'n/a'})",
            f"- Total PnL: {format_money(runtime['total_pnl_usd'])}",
            f"- Total trades: {runtime['total_trades']}",
            f"- Closed trades: {runtime.get('closed_trades', 0)}",
            f"- Open positions: {runtime['open_positions']}",
            f"- Trades today: {runtime['trades_today']}",
            f"- Cycles completed: {runtime['cycles_completed']}",
            f"- Last remote pull: {runtime.get('last_remote_pull_at') or 'unknown'}",
            "",
            "## Polymarket Wallet",
            "",
            f"- Wallet status: {polymarket_wallet.get('status') or 'unknown'}",
            f"- Wallet checked at: {polymarket_wallet.get('checked_at') or 'unknown'}",
        ]
    )

    if polymarket_wallet.get("status") == "ok":
        lines.extend(
            [
                f"- Free collateral: {format_money(polymarket_wallet.get('free_collateral_usd') or 0.0)}",
                f"- Reserved by live orders: {format_money(polymarket_wallet.get('reserved_order_usd') or 0.0)}",
                f"- Live orders: {polymarket_wallet.get('live_orders_count') or 0}",
                f"- Open positions: {polymarket_wallet.get('open_positions_count') or 0}",
                f"- Position mark value: {format_money(polymarket_wallet.get('positions_current_value_usd') or 0.0)}",
                f"- Unrealized PnL: {format_money(polymarket_wallet.get('positions_unrealized_pnl_usd') or 0.0)}",
                f"- Realized PnL: {format_money(polymarket_wallet.get('closed_positions_realized_pnl_usd') or 0.0)}",
                f"- Total observed wallet value: {format_money(polymarket_wallet.get('total_wallet_value_usd') or 0.0)}",
                "",
                "### Wallet Warnings",
                "",
            ]
        )
        wallet_warnings = polymarket_wallet.get("warnings") or ["none"]
        lines.extend(f"- {warning}" for warning in wallet_warnings)
    else:
        lines.extend(
            [
                f"- Wallet probe reason: {polymarket_wallet.get('reason') or 'unknown'}",
                "",
            ]
        )

    lines.extend(
        [
            "## BTC 5-Min Maker",
            "",
            f"- Status: {btc5_maker.get('status') or 'unknown'}",
            f"- Checked at: {btc5_maker.get('checked_at') or 'unknown'}",
        ]
    )
    if btc5_maker.get("status") == "ok":
        latest_trade = btc5_maker.get("latest_trade") or {}
        fill_attribution = btc5_maker.get("fill_attribution") or {}
        best_direction = fill_attribution.get("best_direction") or {}
        best_price_bucket = fill_attribution.get("best_price_bucket") or {}
        recent_summary = fill_attribution.get("recent_live_filled_summary") or {}
        recent_regime = fill_attribution.get("recent_direction_regime") or {}
        lines.extend(
            [
                f"- Live filled rows: {btc5_maker.get('live_filled_rows') or 0}",
                f"- Live filled PnL: {format_money(btc5_maker.get('live_filled_pnl_usd') or 0.0)}",
                f"- Average filled PnL: {format_money(btc5_maker.get('avg_live_filled_pnl_usd') or 0.0)}",
                f"- Latest live fill at: {btc5_maker.get('latest_live_filled_at') or 'unknown'}",
                f"- Latest trade status: {latest_trade.get('order_status') or 'unknown'}",
                f"- Latest trade direction: {latest_trade.get('direction') or 'unknown'}",
                f"- Latest trade PnL: {format_money(latest_trade.get('pnl_usd') or 0.0)}",
                (
                    f"- Best direction: {best_direction.get('label')} "
                    f"({best_direction.get('fills', 0)} fills, {format_money(best_direction.get('pnl_usd') or 0.0)})"
                    if best_direction
                    else "- Best direction: n/a"
                ),
                (
                    f"- Best price bucket: {best_price_bucket.get('label')} "
                    f"({best_price_bucket.get('fills', 0)} fills, {format_money(best_price_bucket.get('pnl_usd') or 0.0)})"
                    if best_price_bucket
                    else "- Best price bucket: n/a"
                ),
                (
                    f"- Recent 12 live fills: {recent_summary.get('fills', 0)} fills, "
                    f"{format_money(recent_summary.get('pnl_usd') or 0.0)} total, "
                    f"{format_money(recent_summary.get('avg_pnl_usd') or 0.0)} avg"
                    if recent_summary
                    else "- Recent 12 live fills: n/a"
                ),
                (
                    f"- Recent regime: favored={recent_regime.get('favored_direction')} "
                    f"weaker={recent_regime.get('weaker_direction')} "
                    f"gap={format_money(recent_regime.get('pnl_gap_usd') or 0.0)} "
                    f"triggered={'yes' if recent_regime.get('triggered') else 'no'}"
                    if recent_regime
                    else "- Recent regime: n/a"
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- BTC 5-min reason: {btc5_maker.get('reason') or 'unknown'}",
                "",
            ]
        )

    lines.extend(
        [
            "## BTC5 Stage Readiness",
            "",
            f"- Can BTC5 trade now: {'yes' if deployment_confidence.get('can_btc5_trade_now') else 'no'}",
            f"- Allowed stage now: {deployment_confidence.get('allowed_stage_label') or 'stage_0'}",
            f"- Stage artifact freshness: {btc5_stage_readiness.get('freshness') or 'unknown'}",
            (
                f"- Probe freshness hours: {btc5_stage_readiness.get('probe_freshness_hours')}"
                if btc5_stage_readiness.get("probe_freshness_hours") is not None
                else "- Probe freshness hours: unknown"
            ),
            "",
            "### Stage 1 Blockers",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in (deployment_confidence.get("stage_1_blockers") or ["none"]))
    lines.extend(["", "### Stage 2 Blockers", ""])
    lines.extend(f"- {item}" for item in (deployment_confidence.get("stage_2_blockers") or ["none"]))
    lines.extend(["", "### Stage 3 Blockers", ""])
    lines.extend(f"- {item}" for item in (deployment_confidence.get("stage_3_blockers") or ["none"]))

    lines.extend(
        [
            "## Service And Validation",
            "",
            f"- Service status: {service['status']}",
            f"- Service detail: {service.get('detail') or 'n/a'}",
            f"- Service checked at: {service.get('checked_at') or 'unknown'}",
            f"- Root regression status: {root_tests['status']}",
            f"- Root regression checked at: {root_tests.get('checked_at') or 'unknown'}",
            f"- Root regression summary: {root_tests.get('display_summary') or root_tests.get('summary') or 'n/a'}",
            f"- Wallet-flow readiness: {wallet_flow['status']}",
            f"- Wallet-flow wallet count: {wallet_flow['wallet_count']}",
            f"- Wallet-flow scores file exists: {'yes' if wallet_flow['scores_exists'] else 'no'}",
            f"- Wallet-flow DB exists: {'yes' if wallet_flow['db_exists'] else 'no'}",
            f"- Wallet-flow last updated: {wallet_flow.get('last_updated') or 'unknown'}",
            "",
            "### Wallet-Flow Reasons",
            "",
        ]
    )

    wallet_reasons = wallet_flow.get("reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in wallet_reasons)
    lines.extend(
        [
            "",
            "## Structural Gates",
            "",
            f"- A-6 status: {gates['a6']['status']}",
            f"- A-6 summary: {gates['a6']['summary']}",
            f"- A-6 maker-fill proxy rate: {_format_optional_float(gates['a6'].get('maker_fill_proxy_rate'))}",
            f"- A-6 violation half-life seconds: {_format_optional_float(gates['a6'].get('violation_half_life_seconds'))}",
            f"- A-6 settlement evidence count: {gates['a6'].get('settlement_evidence_count', 0)}",
            "",
            "### A-6 Blocked Reasons",
            "",
        ]
    )

    a6_reasons = gates["a6"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in a6_reasons)
    lines.extend(
        [
            "",
            f"- B-1 status: {gates['b1']['status']}",
            f"- B-1 summary: {gates['b1']['summary']}",
            f"- B-1 classification accuracy: {_format_optional_pct(gates['b1'].get('classification_accuracy'))}",
            f"- B-1 false positive rate: {_format_optional_pct(gates['b1'].get('false_positive_rate'))}",
            f"- B-1 violation half-life seconds: {_format_optional_float(gates['b1'].get('violation_half_life_seconds'))}",
            "",
            "### B-1 Blocked Reasons",
            "",
        ]
    )

    b1_reasons = gates["b1"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in b1_reasons)
    lines.extend(
        [
            "",
            "## Flywheel",
            "",
            f"- Latest cycle: {flywheel.get('cycle_key') or 'n/a'}",
            f"- Deploy decision: {flywheel.get('decision') or 'n/a'}",
            f"- Reason: {flywheel.get('reason_code') or 'n/a'}",
            f"- Notes: {flywheel.get('notes') or 'n/a'}",
            f"- Summary artifact: {(flywheel.get('artifacts') or {}).get('summary_md', 'n/a')}",
            f"- Scorecard artifact: {(flywheel.get('artifacts') or {}).get('scorecard', 'n/a')}",
            "",
            "## Launch Path",
            "",
            f"- Fast-flow restart ready: {'yes' if launch['fast_flow_restart_ready'] else 'no'}",
            f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
            f"- Next operator action: {launch['next_operator_action']}",
            f"- Launch checklist: {status['artifacts']['launch_checklist']}",
            "",
            "### Launch Blockers",
            "",
        ]
    )

    launch_reasons = launch.get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in launch_reasons)
    lines.extend(
        [
            "",
            "## Runtime Truth",
            "",
            f"- Service status: {truth['service_status']}",
            f"- Cycles completed: {truth['cycles_completed']}",
            f"- Launch blocked: {'yes' if truth['launch_blocked'] else 'no'}",
            f"- Drift detected: {'yes' if truth['drift_detected'] else 'no'}",
            f"- Next action: {truth['next_action']}",
            "",
            "### Drift Reasons",
            "",
        ]
    )

    drift_reasons = truth.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in drift_reasons)
    lines.extend(
        [
            "",
            "## Accounting Reconciliation",
            "",
            f"- Status: {accounting_reconciliation.get('status') or 'unknown'}",
            f"- Drift detected: {'yes' if accounting_reconciliation.get('drift_detected') else 'no'}",
            (
                f"- Local ledger counts: total={((accounting_reconciliation.get('local_ledger_counts') or {}).get('total_trades', 0))}, "
                f"open={((accounting_reconciliation.get('local_ledger_counts') or {}).get('open_positions', 0))}, "
                f"closed={((accounting_reconciliation.get('local_ledger_counts') or {}).get('closed_positions', 0))}"
            ),
            (
                f"- Remote wallet counts: open={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('open_positions', 0))}, "
                f"closed={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('closed_positions', 0))}, "
                f"live_orders={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('live_orders', 0))}"
            ),
            (
                f"- BTC 5-min maker counts: total_rows={((accounting_reconciliation.get('btc_5min_maker_counts') or {}).get('total_rows', 0))}, "
                f"live_filled_rows={((accounting_reconciliation.get('btc_5min_maker_counts') or {}).get('live_filled_rows', 0))}"
            ),
            (
                f"- Unmatched open positions: {((accounting_reconciliation.get('unmatched_open_positions') or {}).get('delta_remote_minus_local', 0)):+d} "
                f"(local={((accounting_reconciliation.get('unmatched_open_positions') or {}).get('local_ledger', 0))}, "
                f"remote={((accounting_reconciliation.get('unmatched_open_positions') or {}).get('remote_wallet', 0))})"
            ),
            (
                f"- Unmatched closed positions: {((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('delta_remote_minus_local', 0)):+d} "
                f"(local={((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('local_ledger', 0))}, "
                f"remote={((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('remote_wallet', 0))})"
            ),
            "",
            "### Reconciliation Drift Reasons",
            "",
        ]
    )
    accounting_drift_reasons = accounting_reconciliation.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in accounting_drift_reasons)
    lines.extend(
        [
            "",
            "## Deployment Confidence",
            "",
            f"- Confidence label: {deployment_confidence.get('confidence_label') or 'unknown'}",
            f"- Freshness score: {_format_optional_float(deployment_confidence.get('freshness_score'))}",
            f"- Accounting coherence score: {_format_optional_float(deployment_confidence.get('accounting_coherence_score'))}",
            f"- Stage readiness score: {_format_optional_float(deployment_confidence.get('stage_readiness_score'))}",
            f"- Confirmation coverage score: {_format_optional_float(deployment_confidence.get('confirmation_coverage_score'))}",
            f"- Validated package ready for live stage 1: {'yes' if ((deployment_confidence.get('validated_package') or {}).get('validated_for_live_stage1')) else 'no'}",
            (
                "- Validated package: "
                + str(
                    ((deployment_confidence.get("validated_package") or {}).get("selected_best_profile_name"))
                    or ((deployment_confidence.get("validated_package") or {}).get("selected_active_profile_name"))
                    or "unknown"
                )
            ),
            f"- Next required artifact: {deployment_confidence.get('next_required_artifact') or 'none'}",
            "",
            "### Deployment Blocking Checks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in (deployment_confidence.get("blocking_checks") or ["none"]))
    lines.extend(
        [
            "",
            "## Source Precedence",
            "",
            f"- Rule: {source_precedence.get('rule') or 'n/a'}",
            "",
            "### Precedence Contradictions",
            "",
        ]
    )
    contradictions = source_precedence.get("contradictions") or []
    if contradictions:
        for item in contradictions:
            if isinstance(item, dict):
                lines.append(f"- {item.get('code')}: {item.get('message')}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Data Cadence",
            "",
            f"- Pull cadence: every {cadence['pull_cadence_minutes']} minutes",
            f"- Full development cycle cadence: every {cadence['full_cycle_cadence_minutes']} minutes",
            f"- Freshness SLA: {cadence['freshness_sla_minutes']} minutes",
            f"- Last remote pull: {cadence.get('last_remote_pull_at') or 'unknown'}",
            f"- Next expected pull: {cadence.get('next_expected_pull_at') or 'unknown'}",
            f"- Current data age: {cadence.get('data_age_minutes') if cadence.get('data_age_minutes') is not None else 'unknown'} minutes",
            f"- Data stale: {'yes' if cadence.get('stale') else 'no'}",
            f"- Next data expectation: {cadence.get('expected_next_data_note') or 'n/a'}",
            "",
            "### Mandatory Extra Pulls",
            "",
        ]
    )

    triggers = cadence.get("manual_pull_triggers") or ["None recorded."]
    lines.extend(f"- {item}" for item in triggers)
    lines.extend(
        [
            "",
            "## Velocity Forecast",
            "",
            f"- Metric: {forecast['metric_name']}",
            f"- Definition: {forecast['definition']}",
            f"- Status: {forecast['status']}",
            f"- Confidence: {forecast['confidence']}",
            f"- Current annualized return run-rate: {forecast['current_annualized_return_pct']:.2f}% ({format_money(forecast['current_annualized_return_usd'])}/year on tracked capital)",
            (
                f"- Next target annualized return run-rate: "
                f"{forecast['next_target_annualized_return_pct']:.2f}% "
                f"({format_money(forecast['next_target_annualized_return_usd'])}/year) "
                f"after about {forecast['next_target_after_hours_of_work']:.1f} more engineering hours"
                if forecast.get("next_target_annualized_return_pct") is not None
                and forecast.get("next_target_after_hours_of_work") is not None
                else "- Next target annualized return run-rate: n/a"
            ),
            f"- Basis: {forecast.get('basis') or 'n/a'}",
            "",
            "### Forecast Assumptions",
            "",
        ]
    )

    assumptions = forecast.get("assumptions") or ["None recorded."]
    lines.extend(f"- {item}" for item in assumptions)
    lines.extend(["", "### Forecast Invalidators", ""])
    invalidators = forecast.get("invalidators") or ["None recorded."]
    lines.extend(f"- {item}" for item in invalidators)
    lines.extend(
        [
            "",
            "## Deployment Finish",
            "",
            f"- Status: {finish['status']}",
            f"- ETA: {finish['eta']}",
            "",
            "### Current Blockers",
            "",
        ]
    )

    blockers = finish.get("blockers") or ["None recorded."]
    lines.extend(f"- {item}" for item in blockers)
    lines.extend(["", "### Exit Criteria", ""])
    exit_criteria = finish.get("exit_criteria") or ["None recorded."]
    lines.extend(f"- {item}" for item in exit_criteria)
    lines.append("")
    return "\n".join(lines)


def format_signed_number(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    number = float(value)
    if number > 0:
        return f"+{number:.6f}"
    return f"{number:.6f}"


def build_operator_digest(report: dict[str, Any], *, launch: dict[str, Any]) -> str:
    candidate_counts = report.get("per_venue_candidate_counts") or {}
    notional = report.get("per_venue_executed_notional_usd") or {}
    thresholds = report.get("active_thresholds") or {}
    budget = report.get("hourly_budget_progress") or {}
    deltas = (report.get("improvement_velocity") or {}).get("deltas") or {}
    reconciliation = report.get("reconciliation_summary") or {}
    next_cycle_metrics = report.get("next_cycle_metrics") or {}
    truth_lattice = ((report.get("strategy_recommendations") or {}).get("truth_lattice") or {})
    open_mismatch = reconciliation.get("unmatched_open_positions") or {}
    closed_mismatch = reconciliation.get("unmatched_closed_positions") or {}
    status_text = "blocked" if launch.get("live_launch_blocked") else "unblocked"
    return (
        "Cycle state: "
        f"launch is {status_text}; "
        f"active thresholds YES={thresholds.get('yes_threshold')} NO={thresholds.get('no_threshold')} "
        f"(max_resolution_hours={thresholds.get('max_resolution_hours')}). "
        f"Candidates PM={candidate_counts.get('polymarket', 0)}, Kalshi={candidate_counts.get('kalshi', 0)}, "
        f"total={candidate_counts.get('total', 0)}. "
        f"Executed notional (last 60m) PM=${float(notional.get('polymarket_hourly') or 0.0):.2f}, "
        f"Kalshi=${float(notional.get('kalshi_hourly') or 0.0):.2f}, "
        f"combined=${float(notional.get('combined_hourly') or 0.0):.2f}. "
        f"Hourly budget used=${float(budget.get('used_usd') or 0.0):.2f}"
        + (
            f" of ${float(budget.get('cap_usd')):.2f} ({float(budget.get('progress_pct')):.2f}%). "
            if budget.get("cap_usd") is not None and budget.get("progress_pct") is not None
            else ". "
        )
        + "Improvement deltas: "
        f"edge_reachability={format_signed_number(deltas.get('edge_reachability_delta'))}, "
        f"candidate_to_trade_conversion={format_signed_number(deltas.get('candidate_to_trade_conversion_delta'))}, "
        f"realized_expected_pnl_drift_usd={format_signed_number(deltas.get('realized_expected_pnl_drift_delta_usd'))}. "
        + "Reconciliation: "
        + (
            "drift detected"
            if reconciliation.get("drift_detected")
            else "reconciled"
        )
        + (
            f" (open delta={int(open_mismatch.get('delta_remote_minus_local') or 0):+d}, "
            f"closed delta={int(closed_mismatch.get('delta_remote_minus_local') or 0):+d}, "
            f"capital delta={format_money(safe_float(reconciliation.get('capital_accounting_delta_usd'), 0.0))})."
        )
        + " Contract mismatches="
        + str(int(next_cycle_metrics.get("contract_mismatch_count") or 0))
        + ", cap breaches="
        + str(int(next_cycle_metrics.get("cap_breach_count") or 0))
        + "."
        + " Truth lattice="
        + str(truth_lattice.get("status") or "unknown")
        + (
            f" ({', '.join(list(truth_lattice.get('broken_reasons') or []))})."
            if truth_lattice.get("broken_reasons")
            else "."
        )
    )


def render_state_improvement_digest_markdown(report: dict[str, Any]) -> str:
    scorecard = report.get("five_metric_scorecard") if isinstance(report.get("five_metric_scorecard"), dict) else {}
    score_metrics = scorecard.get("metrics") if isinstance(scorecard.get("metrics"), dict) else {}
    unresolved_metrics = list(scorecard.get("unresolved_metrics") or [])
    finance_gate = scorecard.get("finance_gate") if isinstance(scorecard.get("finance_gate"), dict) else {}
    finance_blockers = list(finance_gate.get("block_reasons") or [])

    lines = [
        "# State Improvement Digest",
        "",
        f"- Generated: {report.get('generated_at') or 'unknown'}",
        "",
        "## Five-Metric Scorecard",
        "",
        f"- candidate_count: {score_metrics.get('candidate_count')}",
        f"- executed_notional_usd: {score_metrics.get('executed_notional_usd')}",
        f"- candidate_to_trade_conversion: {score_metrics.get('candidate_to_trade_conversion')}",
        f"- recent_resolved_pnl_usd: {score_metrics.get('recent_resolved_pnl_usd')}",
        f"- finance_gate_status: {score_metrics.get('finance_gate_status')}",
        f"- unresolved_metrics: {', '.join(unresolved_metrics) if unresolved_metrics else 'none'}",
        f"- finance_gate_blockers: {', '.join(finance_blockers) if finance_blockers else 'none'}",
        "",
        "## Operator Summary",
        "",
        str(report.get("operator_digest") or "No operator digest available."),
        "",
        "## Structured Fields",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)
