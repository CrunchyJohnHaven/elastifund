from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from nontrading.finance.config import FinanceSettings
from nontrading.finance.executor import FinanceExecutionError
from nontrading.finance.main import build_runtime, run_allocate, run_audit, run_execute, run_sync
from nontrading.finance.models import (
    FinanceAccount,
    FinanceAction,
    FinanceExperiment,
    FinancePosition,
    FinanceRecurringCommitment,
    FinanceSubscription,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_settings(tmp_path: Path, **overrides: object) -> FinanceSettings:
    payload = {
        "db_path": tmp_path / "state" / "jj_finance.db",
        "imports_dir": tmp_path / "imports",
        "reports_dir": tmp_path / "reports" / "finance",
        "workspace_root": tmp_path,
        "autonomy_mode": "shadow",
        "single_action_cap_usd": 250.0,
        "monthly_new_commitment_cap_usd": 1000.0,
        "min_cash_reserve_months": 1.0,
        "equity_treatment": "illiquid_only",
        "whitelist_json": json.dumps(["polymarket_runtime", "jjn_control_plane"]),
    }
    payload.update(overrides)
    return FinanceSettings(**payload)


def seed_external_reports(tmp_path: Path) -> None:
    write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "accounting_reconciliation": {
                "status": "reconciled",
                "capital_accounting_delta_usd": 0.0,
                "unmatched_open_positions": {"absolute_delta": 0},
                "unmatched_closed_positions": {"absolute_delta": 0},
            },
            "btc_5min_maker": {
                "guardrail_recommendation": {
                    "baseline_live_filled_pnl_usd": 120.5,
                    "baseline_live_filled_rows": 123,
                }
            },
            "capital": {
                "polymarket_actual_deployable_usd": 310.0,
            },
            "polymarket_wallet": {
                "total_wallet_value_usd": 360.0,
                "free_collateral_usd": 310.0,
                "open_positions_count": 4,
                "positions_current_value_usd": 50.0,
            },
        },
    )
    write_json(
        tmp_path / "reports" / "nontrading_public_report.json",
        {
            "first_dollar_readiness": {
                "expected_net_cash_30d": 40.0,
                "launchable": False,
                "confidence": 0.2,
            }
        },
    )
    write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "capital_allocation_recommendation": {
                "overall_recommendation": "hold",
                "next_100_usd": {
                    "status": "ready_scale",
                    "blocking_checks": [],
                },
                "next_1000_usd": {
                    "status": "ready_scale",
                    "blocking_checks": [],
                },
                "stage_readiness": {
                    "recommended_stage": 1,
                    "blocking_checks": [],
                },
            }
        },
    )


def test_sync_normalizes_mixed_finance_sources_into_snapshot(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [
            {
                "account_key": "checking",
                "name": "Checking",
                "account_type": "cash",
                "institution": "Chase",
                "balance_usd": 2000.0,
                "available_cash_usd": 2000.0,
            }
        ],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-01-01T00:00:00+00:00",
                "merchant": "Rent",
                "description": "January rent",
                "amount_usd": -800.0,
                "category": "housing",
            },
            {
                "transaction_key": "txn-2",
                "account_key": "checking",
                "posted_at": "2026-02-01T00:00:00+00:00",
                "merchant": "Rent",
                "description": "February rent",
                "amount_usd": -800.0,
                "category": "housing",
            },
        ],
    )
    write_csv(
        settings.imports_dir / "positions.csv",
        [
            {
                "position_key": "equity-1",
                "account_key": "founder",
                "symbol": "STARTUP",
                "asset_type": "startup_equity",
                "quantity": 1,
                "market_value_usd": 50000.0,
            }
        ],
    )
    write_json(
        settings.imports_dir / "subscriptions.json",
        [
            {
                "subscription_key": "sub-chatgpt",
                "vendor": "ChatGPT",
                "product_name": "ChatGPT Plus",
                "category": "ai_assistant",
                "monthly_cost_usd": 20.0,
                "billing_cycle": "monthly",
                "usage_frequency": "weekly",
                "status": "active",
            }
        ],
    )

    store, queue, _ = build_runtime(settings)
    report = run_sync(store, settings)

    assert report["imported_counts"]["accounts"] == 1
    assert report["imported_counts"]["transactions"] == 2
    assert report["imported_counts"]["positions"] == 1
    assert report["imported_counts"]["subscriptions"] == 1
    assert report["recurring_commitments_detected"] == 1
    assert report["rollout_gates"]["classification_precision"] == 1.0
    assert report["rollout_gates"]["snapshot_reconciliation"] == 1.0
    assert report["finance_gate_pass"] is True
    assert report["finance_gate"]["pass"] is True
    assert report["finance_gate"]["status"] == "pass"
    assert report["totals"]["startup_equity_usd"] == 50000.0
    assert report["totals"]["free_cash_after_floor"] == 1490.0
    assert settings.latest_report_path.exists()
    assert queue.list_pending() == []


def test_audit_flags_duplicates_low_usage_and_annual_savings(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_json(
        settings.imports_dir / "subscriptions.json",
        [
            {
                "subscription_key": "sub-chatgpt",
                "vendor": "ChatGPT",
                "product_name": "ChatGPT Plus",
                "category": "ai_assistant",
                "duplicate_group": "ai_assistant",
                "monthly_cost_usd": 20.0,
                "billing_cycle": "monthly",
                "usage_frequency": "unused",
                "status": "active",
                "annual_price_usd": 180.0,
            },
            {
                "subscription_key": "sub-claude",
                "vendor": "Claude",
                "product_name": "Claude Pro",
                "category": "ai_assistant",
                "duplicate_group": "ai_assistant",
                "monthly_cost_usd": 20.0,
                "billing_cycle": "monthly",
                "usage_frequency": "weekly",
                "status": "active",
            },
        ],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-01-05T00:00:00+00:00",
                "merchant": "AWS",
                "description": "Compute",
                "amount_usd": -120.0,
                "category": "compute",
            },
            {
                "transaction_key": "txn-2",
                "account_key": "checking",
                "posted_at": "2026-02-05T00:00:00+00:00",
                "merchant": "AWS",
                "description": "Compute",
                "amount_usd": -120.0,
                "category": "compute",
            },
        ],
    )

    store, queue, _ = build_runtime(settings)
    run_sync(store, settings)
    report = run_audit(store, settings, queue)
    kinds = {finding["kind"] for finding in report["findings"]}

    assert "duplicate_tooling" in kinds
    assert "low_usage_subscription" in kinds
    assert "annual_savings_candidate" in kinds
    assert "overlapping_tool_category" in kinds
    assert settings.subscription_audit_path.exists()
    assert settings.action_queue_path.exists()


def test_allocator_respects_cash_floor_caps_and_ignores_illiquid_equity(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path)
    store, queue, _ = build_runtime(settings)
    store.upsert_account(
        FinanceAccount(
            account_key="checking",
            name="Checking",
            account_type="cash",
            balance_usd=2000.0,
            available_cash_usd=2000.0,
        )
    )
    store.upsert_position(
        FinancePosition(
            position_key="startup-equity",
            account_key="founder",
            symbol="STARTUP",
            asset_type="startup_equity",
            quantity=1.0,
            market_value_usd=10000.0,
        )
    )
    store.upsert_recurring_commitment(
        FinanceRecurringCommitment(
            commitment_key="rent",
            vendor="Rent",
            category="housing",
            amount_usd=900.0,
            monthly_cost_usd=900.0,
            essential=True,
        )
    )
    store.upsert_subscription(
        FinanceSubscription(
            subscription_key="infra",
            vendor="AWS",
            product_name="Compute",
            category="compute",
            monthly_cost_usd=100.0,
            status="active",
        )
    )
    store.upsert_experiment(
        FinanceExperiment(
            experiment_key="tool-upgrade",
            name="Premium data feed",
            budget_usd=600.0,
            monthly_budget_usd=1500.0,
            expected_net_value_30d=80.0,
            expected_information_gain_30d=40.0,
        )
    )

    plan = run_allocate(store, settings, queue)
    ranked = {bucket["bucket"]: bucket for bucket in plan["ranked_buckets"]}

    assert plan["totals"]["capital_ready_to_deploy_usd"] == 1000.0
    assert plan["totals"]["startup_equity_usd"] == 10000.0
    assert ranked["buy_tool_or_data"]["recommended_amount_usd"] == 250.0
    assert ranked["buy_tool_or_data"]["monthly_commitment_usd"] == 1000.0
    assert ranked["fund_trading"]["recommended_amount_usd"] == 250.0
    assert settings.allocation_plan_path.exists()
    assert settings.action_queue_path.exists()


def test_executor_rejects_unwhitelisted_and_oversized_transfers(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, autonomy_mode="live_treasury")
    store, queue, executor = build_runtime(settings)
    store.set_budget_policy("classification_precision", 0.97)
    store.set_budget_policy("snapshot_reconciliation", 0.995)
    store.upsert_account(
        FinanceAccount(
            account_key="checking",
            name="Checking",
            account_type="cash",
            balance_usd=500.0,
            available_cash_usd=500.0,
        )
    )
    queue.sync_actions(
        [
            FinanceAction(
                action_key="transfer::oversized",
                action_type="transfer",
                bucket="fund_trading",
                title="Oversized transfer",
                amount_usd=300.0,
                destination="polymarket_runtime",
                mode_requested="live_treasury",
                idempotency_key="transfer::oversized",
                requires_whitelist=True,
            ),
            FinanceAction(
                action_key="transfer::unwhitelisted",
                action_type="transfer",
                bucket="fund_nontrading",
                title="Unwhitelisted transfer",
                amount_usd=100.0,
                destination="random_wallet",
                mode_requested="live_treasury",
                idempotency_key="transfer::unwhitelisted",
                requires_whitelist=True,
            ),
        ]
    )

    result = executor.execute("live_treasury")
    reasons = {item["action_key"]: item["reason"] for item in result["results"]}
    statuses = {item["action_key"]: item["status"] for item in result["results"]}

    assert reasons["transfer::oversized"] == "single_action_cap_exceeded"
    assert reasons["transfer::unwhitelisted"] == "destination_not_whitelisted"
    assert statuses["transfer::oversized"] == "rejected"
    assert statuses["transfer::unwhitelisted"] == "rejected"


def test_shadow_and_live_modes_enforce_rollout_gates(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store, queue, executor = build_runtime(settings)
    store.upsert_account(
        FinanceAccount(
            account_key="checking",
            name="Checking",
            account_type="cash",
            balance_usd=500.0,
            available_cash_usd=500.0,
        )
    )
    queue.sync_actions(
        [
            FinanceAction(
                action_key="cancel::chatgpt",
                action_type="cancel_subscription",
                bucket="cut_or_cancel",
                title="Cancel ChatGPT",
                amount_usd=20.0,
                mode_requested="live_spend",
                idempotency_key="cancel::chatgpt",
            )
        ]
    )

    shadow = run_execute(store, settings, queue, executor, mode="shadow")
    assert shadow["results"][0]["status"] == "shadowed"

    with pytest.raises(FinanceExecutionError):
        executor.execute("live_spend")
    with pytest.raises(FinanceExecutionError):
        executor.execute("live_treasury")

    store.set_budget_policy("classification_precision", 0.97)
    store.set_budget_policy("snapshot_reconciliation", 0.995)
    queue.sync_actions(
        [
            FinanceAction(
                action_key="cancel::chatgpt",
                action_type="cancel_subscription",
                bucket="cut_or_cancel",
                title="Cancel ChatGPT",
                amount_usd=20.0,
                mode_requested="live_spend",
                idempotency_key="cancel::chatgpt",
            )
        ]
    )

    live_spend = run_execute(store, settings, queue, executor, mode="live_spend")
    assert live_spend["results"][0]["status"] == "executed"

    queue.sync_actions(
        [
            FinanceAction(
                action_key="transfer::trading",
                action_type="transfer",
                bucket="fund_trading",
                title="Fund trading",
                amount_usd=100.0,
                destination="polymarket_runtime",
                mode_requested="live_treasury",
                idempotency_key="transfer::trading",
                requires_whitelist=True,
            )
        ]
    )
    live_treasury = run_execute(store, settings, queue, executor, mode="live_treasury")
    assert live_treasury["results"][0]["status"] == "executed"


def test_run_execute_falls_back_to_shadow_when_live_treasury_whitelist_blocks(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path, autonomy_mode="live_treasury", whitelist_json="[]")
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Polymarket",
                "description": "Funding",
                "amount_usd": -50.0,
                "category": "trading",
            }
        ],
    )

    store, queue, executor = build_runtime(settings)
    run_sync(store, settings)
    run_allocate(store, settings, queue)

    report = run_execute(store, settings, queue, executor, mode="live_treasury")
    queue_report = json.loads(settings.action_queue_path.read_text(encoding="utf-8"))
    action_rows = {item["action_key"]: item for item in queue_report["actions"]}

    assert report["mode"] == "shadow"
    assert report["requested_mode"] == "live_treasury"
    assert report["finance_gate_pass"] is False
    assert report["rollout_gates"]["classification_precision"] == 1.0
    assert report["rollout_gates"]["snapshot_reconciliation"] == 1.0
    assert report["live_hold"]["destination"] == "polymarket_runtime"
    assert report["live_hold"]["destination_whitelisted"] is False
    assert report["live_hold"]["status"] == "hold_repair"
    assert report["live_hold"]["policy_checks"]["whitelist_destination_pass"] is False
    assert "JJ_FINANCE_WHITELIST_JSON" in report["live_hold"]["remediation"]
    assert report["results"][0]["action_key"] == "allocate::fund_trading"
    assert report["results"][0]["status"] == "shadowed"
    assert action_rows["allocate::fund_trading"]["status"] == "shadowed"
    assert action_rows["allocate::fund_nontrading"]["status"] == "queued"


def test_live_treasury_executes_only_top_trading_action(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path, autonomy_mode="live_treasury")
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Polymarket",
                "description": "Funding",
                "amount_usd": -50.0,
                "category": "trading",
            }
        ],
    )

    store, queue, executor = build_runtime(settings)
    run_sync(store, settings)
    run_audit(store, settings, queue)
    run_allocate(store, settings, queue)

    report = run_execute(store, settings, queue, executor, mode="live_treasury")
    queue_report = json.loads(settings.action_queue_path.read_text(encoding="utf-8"))
    action_rows = {item["action_key"]: item for item in queue_report["actions"]}

    assert report["finance_gate_pass"] is True
    assert [item["action_key"] for item in report["results"]] == ["allocate::fund_trading"]
    assert report["results"][0]["status"] == "executed"
    assert action_rows["allocate::fund_trading"]["status"] == "executed"
    assert action_rows["allocate::fund_nontrading"]["status"] == "queued"
    assert "allocate::cut_or_cancel" not in action_rows


def test_audit_skips_zero_dollar_subscription_cancels(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_json(
        settings.imports_dir / "subscriptions.json",
        [
            {
                "subscription_key": "sub-polymarket",
                "vendor": "Polymarket",
                "product_name": "Trading balance",
                "category": "trading_capital",
                "monthly_cost_usd": 0.0,
                "billing_cycle": "monthly",
                "usage_frequency": "unused",
                "status": "active",
            }
        ],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Polymarket",
                "description": "Trading balance",
                "amount_usd": 0.0,
                "category": "trading",
            }
        ],
    )

    store, queue, _ = build_runtime(settings)
    run_sync(store, settings)
    run_audit(store, settings, queue)

    queue_report = json.loads(settings.action_queue_path.read_text(encoding="utf-8"))
    action_keys = {item["action_key"] for item in queue_report["actions"]}

    assert "audit::unused_subscription::polymarket" not in action_keys


def test_run_allocate_holds_incremental_trading_capital_and_caps_nontrading_budget(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    write_json(
        tmp_path / "reports" / "launch_packet_latest.json",
        {
            "contract": {"service_state": "stopped"},
            "launch_state": {
                "storage": {"blocked": True},
                "package_load": {"runtime_package_loaded": False},
            },
        },
    )
    write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        {
            "metrics": {"candidate_to_trade_conversion": 0.0},
            "per_venue_executed_notional_usd": {"combined_hourly": 0.0},
        },
    )
    write_json(
        tmp_path / "reports" / "nontrading_cycle_packet.json",
        {
            "cycle_verdict": "manual_close_ready_now",
        },
    )
    write_json(
        tmp_path / "reports" / "nontrading_public_report.json",
        {
            "allocator_input": {
                "required_budget": 12.0,
                "confidence": 0.28,
                "expected_net_cash_30d": 0.0,
                "capacity_limits": {"budget_usd": 12.0},
            },
            "first_dollar_readiness": {
                "expected_net_cash_30d": 0.0,
                "launchable": False,
                "confidence": 0.28,
            },
        },
    )
    write_json(
        tmp_path / "reports" / "finance" / "action_queue.json",
        {
            "actions": [
                {
                    "action_key": "allocate::fund_trading",
                    "status": "executed",
                    "amount_usd": 250.0,
                }
            ]
        },
    )
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Rent",
                "description": "Rent",
                "amount_usd": -50.0,
                "category": "housing",
            }
        ],
    )

    store, queue, _ = build_runtime(settings)
    run_sync(store, settings)
    plan = run_allocate(store, settings, queue)
    action_rows = {item.action_key: item for item in queue.list_pending()}
    ranked = {bucket["bucket"]: bucket for bucket in plan["ranked_buckets"]}

    assert ranked["fund_trading"]["recommended_amount_usd"] == 0.0
    assert ranked["fund_trading"]["metadata"]["release_blockers"] == [
        "service_not_running",
        "remote_runtime_storage_blocked",
        "runtime_package_load_pending",
        "executed_notional_zero_across_current_cycle",
        "candidate_to_trade_conversion_zero_across_current_cycle",
    ]
    assert ranked["fund_nontrading"]["recommended_amount_usd"] == 12.0
    assert ranked["fund_nontrading"]["metadata"]["allocation_cap_usd"] == 12.0
    assert "allocate::fund_trading" not in action_rows
    assert action_rows["allocate::fund_nontrading"].amount_usd == 12.0


def test_run_allocate_uses_strategy_scale_hold_to_keep_trading_size_flat(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    write_json(
        tmp_path / "reports" / "launch_packet_latest.json",
        {
            "contract": {"service_state": "running"},
            "launch_state": {
                "storage": {"blocked": False},
                "package_load": {"runtime_package_loaded": True},
            },
        },
    )
    write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        {
            "metrics": {"candidate_to_trade_conversion": 0.42},
            "per_venue_executed_notional_usd": {"combined_hourly": 25.0},
        },
    )
    write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "capital_allocation_recommendation": {
                "overall_recommendation": "btc5_shadow_only",
                "next_100_usd": {
                    "status": "hold",
                    "blocking_checks": ["higher_notional_live_validation_missing"],
                },
                "next_1000_usd": {
                    "status": "hold",
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
                "stage_readiness": {
                    "recommended_stage": 1,
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
            }
        },
    )
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Rent",
                "description": "Rent",
                "amount_usd": -50.0,
                "category": "housing",
            }
        ],
    )

    store, queue, _ = build_runtime(settings)
    run_sync(store, settings)
    plan = run_allocate(store, settings, queue)
    ranked = {bucket["bucket"]: bucket for bucket in plan["ranked_buckets"]}

    assert ranked["fund_trading"]["recommended_amount_usd"] == 0.0
    assert ranked["fund_trading"]["metadata"]["finance_state"] == "hold_no_spend"
    assert ranked["fund_trading"]["metadata"]["capital_expansion_blockers"][:2] == [
        "next_100_live_hold",
        "next_1000_live_hold",
    ]
    assert "higher_notional_live_validation_missing" in ranked["fund_trading"]["metadata"]["capital_expansion_blockers"]
    assert "Keep BTC5 size flat at stage 1" in ranked["fund_trading"]["rationale"]
    assert all(action.bucket != "fund_trading" for action in queue.list_pending())


def test_run_execute_emits_explicit_hold_no_spend_when_scale_policy_blocks_expansion(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "capital_allocation_recommendation": {
                "overall_recommendation": "btc5_shadow_only",
                "next_100_usd": {
                    "status": "hold",
                    "blocking_checks": ["higher_notional_live_validation_missing"],
                },
                "next_1000_usd": {
                    "status": "hold",
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
                "stage_readiness": {
                    "recommended_stage": 1,
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
            }
        },
    )
    settings = make_settings(tmp_path, autonomy_mode="live_treasury")
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Rent",
                "description": "Rent",
                "amount_usd": -50.0,
                "category": "housing",
            }
        ],
    )

    store, queue, executor = build_runtime(settings)
    run_sync(store, settings)
    result = run_execute(store, settings, queue, executor, mode="live_treasury")
    latest = json.loads(settings.latest_report_path.read_text(encoding="utf-8"))

    assert result["finance_gate_pass"] is False
    assert result["finance_state"] == "hold_no_spend"
    assert result["live_hold"]["status"] == "hold_no_spend"
    assert result["live_hold"]["reason"].startswith("hold_no_spend:")
    assert "next_100_live_hold" in result["live_hold"]["block_reasons"]
    assert "higher_notional_live_validation_missing" in result["live_hold"]["block_reasons"]
    assert latest["finance_gate_pass"] is False
    assert latest["finance_state"] == "hold_no_spend"
    assert latest["finance_gate"]["reason"].startswith("hold_no_spend:")


def test_sync_allows_stage1_baseline_while_treasury_expansion_stays_held(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "accounting_reconciliation": {
                "status": "reconciled",
                "capital_accounting_delta_usd": 0.0,
                "unmatched_open_positions": {"absolute_delta": 0},
                "unmatched_closed_positions": {"absolute_delta": 0},
            },
            "allow_order_submission": True,
            "btc5_selected_package": {
                "runtime_package_loaded": True,
            },
            "capital": {
                "deployed_capital_usd": 17.58,
                "reserved_order_usd": 17.58,
            },
            "polymarket_wallet": {
                "total_wallet_value_usd": 360.0,
                "free_collateral_usd": 310.0,
                "open_positions_count": 4,
                "positions_current_value_usd": 50.0,
            },
        },
    )
    write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "capital_allocation_recommendation": {
                "overall_recommendation": "btc5_shadow_only",
                "next_100_usd": {
                    "status": "hold",
                    "blocking_checks": ["higher_notional_live_validation_missing"],
                },
                "next_1000_usd": {
                    "status": "hold",
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
                "stage_readiness": {
                    "recommended_stage": 0,
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
            }
        },
    )
    settings = make_settings(tmp_path)
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Rent",
                "description": "Rent",
                "amount_usd": -50.0,
                "category": "housing",
            }
        ],
    )

    store, _, _ = build_runtime(settings)
    report = run_sync(store, settings)

    assert report["finance_gate_pass"] is True
    assert report["baseline_live_trading_pass"] is True
    assert report["treasury_gate_pass"] is False
    assert report["capital_expansion_only_hold"] is True
    assert report["finance_state"] == "hold_no_spend"
    assert report["finance_gate"]["pass"] is True
    assert report["finance_gate"]["treasury_pass"] is False
    assert report["finance_gate"]["capital_expansion_only_hold"] is True
    assert report["finance_gate"]["stage_cap"] == 1


def test_run_execute_executes_explicit_stage1_maintenance_action_when_only_expansion_is_held(tmp_path: Path) -> None:
    seed_external_reports(tmp_path)
    write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "accounting_reconciliation": {
                "status": "reconciled",
                "capital_accounting_delta_usd": 0.0,
                "unmatched_open_positions": {"absolute_delta": 0},
                "unmatched_closed_positions": {"absolute_delta": 0},
            },
            "allow_order_submission": True,
            "btc5_selected_package": {
                "runtime_package_loaded": True,
            },
            "capital": {
                "deployed_capital_usd": 17.58,
                "reserved_order_usd": 17.58,
            },
            "polymarket_wallet": {
                "total_wallet_value_usd": 360.0,
                "free_collateral_usd": 310.0,
                "open_positions_count": 4,
                "positions_current_value_usd": 50.0,
            },
        },
    )
    write_json(
        tmp_path / "reports" / "strategy_scale_comparison.json",
        {
            "capital_allocation_recommendation": {
                "overall_recommendation": "btc5_shadow_only",
                "next_100_usd": {
                    "status": "hold",
                    "blocking_checks": ["higher_notional_live_validation_missing"],
                },
                "next_1000_usd": {
                    "status": "hold",
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
                "stage_readiness": {
                    "recommended_stage": 0,
                    "blocking_checks": ["trailing_40_live_filled_not_positive"],
                },
            }
        },
    )
    settings = make_settings(tmp_path, autonomy_mode="live_treasury")
    write_csv(
        settings.imports_dir / "accounts.csv",
        [{"account_key": "checking", "name": "Checking", "account_type": "cash", "balance_usd": 1000.0, "available_cash_usd": 1000.0}],
    )
    write_csv(
        settings.imports_dir / "transactions.csv",
        [
            {
                "transaction_key": "txn-1",
                "account_key": "checking",
                "posted_at": "2026-03-10T00:00:00+00:00",
                "merchant": "Rent",
                "description": "Rent",
                "amount_usd": -50.0,
                "category": "housing",
            }
        ],
    )

    store, queue, executor = build_runtime(settings)
    run_sync(store, settings)
    plan = run_allocate(store, settings, queue)
    queue_rows = {action.action_key: action for action in queue.list_pending()}

    assert any(action["action_key"] == "allocate::maintain_stage1_flat_size" for action in plan["recommended_actions"])
    assert "allocate::maintain_stage1_flat_size" in queue_rows
    assert queue_rows["allocate::maintain_stage1_flat_size"].amount_usd == 0.0
    assert queue_rows["allocate::maintain_stage1_flat_size"].status == "queued"

    result = run_execute(store, settings, queue, executor, mode="live_treasury")
    latest = json.loads(settings.latest_report_path.read_text(encoding="utf-8"))
    queue_report = json.loads(settings.action_queue_path.read_text(encoding="utf-8"))
    action_rows = {item["action_key"]: item for item in queue_report["actions"]}

    assert result["finance_gate_pass"] is True
    assert result["treasury_gate_pass"] is False
    assert result["finance_state"] == "hold_no_spend"
    assert [item["action_key"] for item in result["results"]] == ["allocate::maintain_stage1_flat_size"]
    assert result["results"][0]["status"] == "executed"
    assert latest["finance_gate_pass"] is True
    assert latest["treasury_gate_pass"] is False
    assert latest["capital_expansion_only_hold"] is True
    assert latest["finance_state"] == "hold_no_spend"
    assert latest["finance_gate"]["pass"] is True
    assert latest["finance_gate"]["treasury_pass"] is False
    assert latest["finance_gate"]["capital_expansion_only_hold"] is True
    assert latest["finance_gate"]["reason"].startswith("hold_no_spend:")
    assert action_rows["allocate::maintain_stage1_flat_size"]["status"] == "executed"


def test_reports_emit_machine_readable_gaps_when_sources_are_missing(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store, queue, executor = build_runtime(settings)

    sync_report = run_sync(store, settings)
    audit_report = run_audit(store, settings, queue)
    allocation_plan = run_allocate(store, settings, queue)
    execute_report = run_execute(store, settings, queue, executor, mode="shadow")

    assert "accounts_import_missing" in sync_report["gaps"]
    assert "transactions_import_missing" in sync_report["gaps"]
    assert "runtime_truth_missing" in sync_report["gaps"]
    assert "subscriptions_missing" in audit_report["gaps"]
    assert "runtime_truth_missing" in allocation_plan["gaps"]
    assert "nontrading_public_report_missing" in allocation_plan["gaps"]
    assert execute_report["mode"] == "shadow"
    assert settings.latest_report_path.exists()
    assert settings.subscription_audit_path.exists()
    assert settings.allocation_plan_path.exists()
    assert settings.action_queue_path.exists()


def test_allocate_tolerates_missing_guardrail_recommendation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "btc_5min_maker": {
                "guardrail_recommendation": None,
            }
        },
    )
    write_json(
        tmp_path / "reports" / "nontrading_public_report.json",
        {
            "first_dollar_readiness": {
                "expected_net_cash_30d": 10.0,
                "launchable": False,
                "confidence": 0.5,
            }
        },
    )
    store, queue, _executor = build_runtime(settings)

    allocation_plan = run_allocate(store, settings, queue)

    assert allocation_plan["gaps"] == ["audit_not_run"]
    assert settings.allocation_plan_path.exists()
