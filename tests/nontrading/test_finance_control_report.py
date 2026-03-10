from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nontrading.finance import FinancePolicy
from scripts.render_finance_control_report import build_finance_control_report, write_json_artifact


def test_finance_report_handles_missing_optional_sources_with_machine_readable_gaps(tmp_path: Path) -> None:
    runtime_truth = {
        "accounting_reconciliation": {
            "drift_detected": True,
            "capital_accounting_delta_usd": -75.0,
            "drift_reasons": ["ledger_wallet_mismatch"],
            "remote_wallet_counts": {"free_collateral_usd": 310.0},
            "unmatched_open_positions": {"absolute_delta": 2},
            "unmatched_closed_positions": {"absolute_delta": 9},
        },
        "btc_5min_maker": {
            "live_filled_rows": 42,
            "fill_attribution": {
                "recent_live_filled_summary": {"fills": 12, "pnl_usd": 4.2},
            },
        },
    }
    state_improvement = {
        "strategy_recommendations": {
            "public_performance_scoreboard": {
                "deploy_recommendation": "promote",
                "forecast_confidence_label": "medium",
                "realized_btc5_sleeve_run_rate_pct": 1200.0,
            },
            "capital_addition_readiness": {
                "polymarket_btc5": {
                    "status": "hold",
                    "blocking_checks": ["accounting_reconciliation_drift"],
                    "confidence_label": "medium",
                    "reasons": ["reconcile_first"],
                }
            },
        }
    }
    nontrading_report = {
        "allocator_input": {
            "required_budget": 12.0,
            "confidence": 0.2,
            "expected_net_cash_30d": 40.0,
            "compliance_status": "warning",
            "capacity_limits": {"budget_usd": 12.0},
        },
        "funnel": {"researched_accounts": 3},
        "first_dollar_readiness": {
            "status": "setup_only",
            "launchable": False,
            "blocking_reasons": [
                "checkout_surface_not_ready",
                "billing_webhook_not_ready",
            ],
            "expected_net_cash_30d": 40.0,
        },
    }

    runtime_truth_path = tmp_path / "runtime_truth_latest.json"
    state_improvement_path = tmp_path / "state_improvement_latest.json"
    nontrading_report_path = tmp_path / "nontrading_public_report.json"
    write_json_artifact(runtime_truth, runtime_truth_path)
    write_json_artifact(state_improvement, state_improvement_path)
    write_json_artifact(nontrading_report, nontrading_report_path)

    latest, allocation = build_finance_control_report(
        policy=FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0),
        runtime_truth_path=runtime_truth_path,
        state_improvement_path=state_improvement_path,
        nontrading_report_path=nontrading_report_path,
        nontrading_status_path=tmp_path / "missing_nontrading_status.json",
        finance_snapshot_path=tmp_path / "missing_snapshot.json",
        subscription_audit_path=tmp_path / "missing_subscription_audit.json",
        action_queue_path=tmp_path / "missing_action_queue.json",
        workflow_mining_summary_path=tmp_path / "missing_workflow_mining.json",
    )

    gap_codes = {item["code"] for item in latest["gaps"]}
    candidate_ids = {item["candidate_id"] for item in allocation["ranked_actions"]}

    assert latest["metrics"]["free_cash_after_floor"] == 0.0
    assert latest["metrics"]["capital_ready_to_deploy_usd"] == 0.0
    assert latest["finance_gate"]["reason"] == "finance_action_queue_missing"
    assert "finance_snapshot_missing" in gap_codes
    assert "subscription_audit" in gap_codes
    assert "finance_action_queue" in gap_codes
    assert "workflow_mining" in gap_codes
    assert "buy_data_finance_imports" in candidate_ids
    assert latest["allocation_plan"]["resource_asks"]
    ranking_rows = latest["allocator_rankings_batch"]["candidate_rankings"]
    finance_import_row = next(item for item in ranking_rows if item["candidate_id"] == "buy_data_finance_imports")
    assert finance_import_row["model_tier"] == "routine_ingestion"
    assert latest["cycle_budget_ledger"]["model_minutes"]["requested_total"] == 35.0
    assert latest["cycle_budget_ledger"]["model_minutes"]["requested_cheap"] == 35.0
    assert latest["allocation_plan_summary"]["resource_ask_count"] >= 1

    latest_path = tmp_path / "reports" / "finance" / "latest.json"
    allocation_path = tmp_path / "reports" / "finance" / "allocation_plan.json"
    write_json_artifact(latest, latest_path)
    write_json_artifact(allocation, allocation_path)

    written_latest = json.loads(latest_path.read_text(encoding="utf-8"))
    written_allocation = json.loads(allocation_path.read_text(encoding="utf-8"))

    assert written_latest["schema_version"] == "finance_control_report.v1"
    assert written_allocation["schema_version"] == "finance_allocation_plan.v1"
    assert written_allocation["summary"]["resource_ask_count"] >= 1


def test_finance_report_preserves_last_execute_and_names_next_queued_action(tmp_path: Path) -> None:
    runtime_truth = {
        "btc_5min_maker": {
            "live_filled_rows": 138,
            "fill_attribution": {
                "recent_live_filled_summary": {"fills": 12, "pnl_usd": -8.55},
            },
        }
    }
    nontrading_report = {
        "allocator_input": {
            "required_budget": 250.0,
            "confidence": 0.28,
            "expected_net_cash_30d": 0.0,
        }
    }
    nontrading_status = {
        "launchable": False,
        "blocking_reasons": [
            "checkout_surface_not_ready",
            "billing_webhook_not_ready",
        ],
    }
    finance_snapshot = {
        "schema_version": "finance_latest.v1",
        "generated_at": "2026-03-10T21:14:53+00:00",
        "last_execute": {
            "schema_version": "finance_execute.v1",
            "generated_at": "2026-03-10T21:15:01+00:00",
            "mode": "live_treasury",
            "finance_gate_pass": True,
            "policy_checks": {
                "destination": "polymarket_runtime",
                "destination_whitelisted": True,
                "whitelist_destination_pass": True,
            },
            "results": [
                {
                    "action_key": "allocate::fund_trading",
                    "status": "executed",
                }
            ],
        },
        "totals": {
            "capital_ready_to_deploy_usd": 597.48,
            "monthly_burn_usd": 0.0,
            "startup_equity_usd": 0.0,
        },
    }
    action_queue = {
        "actions": [
            {
                "action_key": "allocate::fund_trading",
                "bucket": "fund_trading",
                "destination": "polymarket_runtime",
                "amount_usd": 250.0,
                "priority_score": 86.3,
                "status": "executed",
                "reason": "BTC5 runtime truth remains the highest-confidence capital deployment lane.",
            },
            {
                "action_key": "allocate::fund_nontrading",
                "bucket": "fund_nontrading",
                "destination": "jjn_control_plane",
                "amount_usd": 250.0,
                "priority_score": 18.0,
                "status": "queued",
                "reason": "JJ-N still offers information gain even while first-dollar gates are open.",
            },
        ]
    }

    runtime_truth_path = tmp_path / "runtime_truth_latest.json"
    state_improvement_path = tmp_path / "state_improvement_latest.json"
    nontrading_report_path = tmp_path / "nontrading_public_report.json"
    nontrading_status_path = tmp_path / "nontrading_first_dollar_status.json"
    finance_snapshot_path = tmp_path / "finance_latest.json"
    action_queue_path = tmp_path / "action_queue.json"
    write_json_artifact(runtime_truth, runtime_truth_path)
    write_json_artifact({}, state_improvement_path)
    write_json_artifact(nontrading_report, nontrading_report_path)
    write_json_artifact(nontrading_status, nontrading_status_path)
    write_json_artifact(finance_snapshot, finance_snapshot_path)
    write_json_artifact(action_queue, action_queue_path)

    latest, _ = build_finance_control_report(
        policy=FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0),
        runtime_truth_path=runtime_truth_path,
        state_improvement_path=state_improvement_path,
        nontrading_report_path=nontrading_report_path,
        nontrading_status_path=nontrading_status_path,
        finance_snapshot_path=finance_snapshot_path,
        subscription_audit_path=tmp_path / "missing_subscription_audit.json",
        action_queue_path=action_queue_path,
        workflow_mining_summary_path=tmp_path / "missing_workflow_mining.json",
    )

    assert latest["finance_gate"]["pass"] is True
    assert latest["finance_gate"]["reason"] == "executed"
    assert latest["finance_gate_pass"] is True
    assert latest["last_execute"]["mode"] == "live_treasury"
    assert latest["one_next_cycle_action"]["action_key"] == "allocate::fund_nontrading"
    assert latest["one_next_cycle_action"]["status"] == "queued_until_launchable"
    assert latest["one_next_cycle_action"]["blocking_reasons"] == [
        "checkout_surface_not_ready",
        "billing_webhook_not_ready",
    ]
