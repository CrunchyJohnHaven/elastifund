from __future__ import annotations

import json
from pathlib import Path

from nontrading.finance.model_budget import build_model_budget_plan
from scripts.run_instance5_model_budget_allocator import update_action_queue


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_build_model_budget_plan_splits_research_spend_from_treasury_hold() -> None:
    finance_latest = {
        "generated_at": "2026-03-12T13:08:48+00:00",
        "finance_gate_pass": True,
        "finance_state": "hold_no_spend",
        "capital_expansion_only_hold": True,
        "treasury_gate_pass": False,
        "totals": {
            "capital_ready_to_deploy_usd": 672.06,
        },
        "finance_gate": {
            "reason": "hold_no_spend:stage_upgrade_probe_stale",
            "remediation": "Keep size flat and repair launch truth.",
        },
        "rollout_gates": {
            "ready_for_live_spend": True,
        },
    }
    action_queue = {
        "generated_at": "2026-03-12T13:08:48+00:00",
        "actions": [
            {
                "action_key": "allocate::maintain_stage1_flat_size",
                "status": "executed",
                "monthly_commitment_usd": 0.0,
            }
        ],
    }
    runtime_truth = {
        "generated_at": "2026-03-12T13:45:54+00:00",
        "btc5_stage_readiness": {
            "baseline_live_allowed": True,
            "ready_for_stage_1": False,
        },
    }

    plan, queued_actions = build_model_budget_plan(
        finance_latest=finance_latest,
        action_queue=action_queue,
        runtime_truth=runtime_truth,
        now="2026-03-12T14:00:00+00:00",
    )

    assert plan["schema_version"] == "model_budget_plan.v1"
    assert plan["required_outputs"]["candidate_delta_arr_bps"] == 190
    assert plan["required_outputs"]["expected_improvement_velocity_delta"] == "+14%"
    assert plan["required_outputs"]["arr_confidence_score"] == 0.78
    assert plan["required_outputs"]["block_reasons"] == [
        "llm_budget_not_queued",
        "trading_treasury_expansion_blocked_but_research_spend_not_split",
    ]
    assert plan["required_outputs"]["finance_gate_pass"] is True
    assert plan["policy_snapshot"]["research_spend_mode_allowed"] is True
    assert [item["monthly_budget_usd"] for item in plan["operating_points"]] == [200.0, 400.0, 800.0]
    assert plan["queue_package"]["monthly_total_usd"] == 200.0
    assert plan["queue_package"]["status"] == "queued"
    assert len(queued_actions) == 3
    assert all(action["mode_requested"] == "live_spend" for action in queued_actions)
    assert all(action["amount_usd"] <= 250.0 for action in queued_actions)


def test_update_action_queue_is_idempotent_for_pilot_actions() -> None:
    action_queue = {
        "schema_version": "finance_action_queue.v1",
        "generated_at": "2026-03-12T13:08:48+00:00",
        "summary": {"queued": 0, "shadowed": 0, "executed": 1, "rejected": 0},
        "actions": [
            {
                "id": 1,
                "action_key": "allocate::maintain_stage1_flat_size",
                "status": "executed",
                "monthly_commitment_usd": 0.0,
                "created_at": "2026-03-12T13:08:48+00:00",
                "updated_at": "2026-03-12T13:08:48+00:00",
            }
        ],
    }
    finance_latest = {
        "finance_gate_pass": True,
        "finance_state": "hold_no_spend",
        "capital_expansion_only_hold": True,
        "treasury_gate_pass": False,
        "totals": {"capital_ready_to_deploy_usd": 672.06},
        "finance_gate": {"reason": "hold_no_spend", "remediation": "repair"},
        "rollout_gates": {"ready_for_live_spend": True},
    }
    runtime_truth = {"btc5_stage_readiness": {"baseline_live_allowed": True, "ready_for_stage_1": False}}

    plan, queued_actions = build_model_budget_plan(
        finance_latest=finance_latest,
        action_queue=action_queue,
        runtime_truth=runtime_truth,
        now="2026-03-12T14:00:00+00:00",
    )
    assert plan["queue_package"]["policy_compliant"] is True

    updated_once = update_action_queue(
        action_queue=action_queue,
        queued_actions=queued_actions,
        generated_at="2026-03-12T14:00:00+00:00",
    )
    updated_twice = update_action_queue(
        action_queue=updated_once,
        queued_actions=queued_actions,
        generated_at="2026-03-12T14:05:00+00:00",
    )

    keys = [item["action_key"] for item in updated_twice["actions"]]
    assert keys.count("allocate::autoprompt_api_credits_pilot") == 1
    assert keys.count("allocate::autoprompt_eval_compute_pilot") == 1
    assert keys.count("allocate::autoprompt_artifact_io_pilot") == 1
    assert updated_twice["summary"] == {"queued": 3, "shadowed": 0, "executed": 1, "rejected": 0}
