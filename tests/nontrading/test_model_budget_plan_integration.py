from __future__ import annotations

import json
from pathlib import Path

from nontrading.finance.action_queue import FinanceActionQueue
from nontrading.finance.config import FinanceSettings
from nontrading.finance.main import run_allocate
from nontrading.finance.store import FinanceStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_run_allocate_emits_model_budget_plan_and_autoprompt_queue_actions(tmp_path: Path) -> None:
    workspace_root = tmp_path
    reports_finance = workspace_root / "reports" / "finance"
    reports_finance.mkdir(parents=True, exist_ok=True)

    finance_latest = {
        "schema_version": "finance_latest.v1",
        "generated_at": "2026-03-12T13:08:48+00:00",
        "finance_gate_pass": True,
        "finance_state": "hold_no_spend",
        "capital_expansion_only_hold": True,
        "treasury_gate_pass": False,
        "totals": {
            "capital_ready_to_deploy_usd": 672.06,
            "free_cash_after_floor": 672.06,
            "liquid_cash_usd": 672.06,
            "monthly_burn_usd": 0.0,
        },
        "finance_gate": {
            "reason": "hold_no_spend:stage_upgrade_probe_stale",
            "remediation": "Keep size flat and repair launch truth.",
        },
        "rollout_gates": {
            "ready_for_live_spend": True,
            "ready_for_live_treasury": True,
            "classification_precision": 1.0,
            "snapshot_reconciliation": 1.0,
            "reasons": [],
        },
    }
    runtime_truth = {
        "generated_at": "2026-03-12T13:45:54+00:00",
        "btc5_stage_readiness": {
            "baseline_live_allowed": True,
            "ready_for_stage_1": False,
        },
        "btc_5min_maker": {
            "guardrail_recommendation": {
                "baseline_live_filled_pnl_usd": 0.0,
                "baseline_live_filled_rows": 0,
            }
        },
    }
    subscription_audit = {"findings": [], "gaps": []}
    allocation_plan_seed = {
        "schema_version": "finance_allocation_plan.v1",
        "recommended_actions": [],
        "ranked_buckets": [],
        "totals": finance_latest["totals"],
        "gaps": [],
    }

    _write_json(reports_finance / "latest.json", finance_latest)
    _write_json(reports_finance / "subscription_audit.json", subscription_audit)
    _write_json(reports_finance / "allocation_plan.json", allocation_plan_seed)
    _write_json(workspace_root / "reports" / "runtime_truth_latest.json", runtime_truth)

    settings = FinanceSettings(
        db_path=workspace_root / "state" / "jj_finance.db",
        reports_dir=reports_finance,
        workspace_root=workspace_root,
        whitelist_json="[]",
    )
    settings.ensure_paths()
    store = FinanceStore(settings.db_path, settings=settings)
    store.record_snapshot("sync", finance_latest["schema_version"], finance_latest)
    store.record_snapshot("audit", "finance_subscription_audit.v1", subscription_audit)
    queue = FinanceActionQueue(store)

    run_allocate(store, settings, queue)

    model_budget_path = reports_finance / "model_budget_plan.json"
    action_queue_path = reports_finance / "action_queue.json"
    assert model_budget_path.exists()
    assert action_queue_path.exists()

    model_budget = json.loads(model_budget_path.read_text(encoding="utf-8"))
    queue_payload = json.loads(action_queue_path.read_text(encoding="utf-8"))

    assert model_budget["schema_version"] == "model_budget_plan.v1"
    assert model_budget["queue_package"]["operating_point"] == "pilot"
    assert model_budget["queue_package"]["status"] == "queued"
    assert model_budget["queue_package"]["monthly_total_usd"] == 200.0
    assert model_budget["queue_package"]["policy_compliant"] is True

    autoprompt_actions = [
        item for item in queue_payload["actions"] if item["action_key"].startswith("allocate::autoprompt_")
    ]
    assert len(autoprompt_actions) == 3
    assert all(item["status"] == "queued" for item in autoprompt_actions)
    assert {item["vendor"] for item in autoprompt_actions} == {
        "api_credits_pool",
        "comparison_bench_compute",
        "artifact_retention_io",
    }
