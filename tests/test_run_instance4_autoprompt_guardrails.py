from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from orchestration.autoprompting.contracts import (
    build_merge_decision,
    build_provider_boundary_matrix,
    build_worker_adapter_contract,
    evaluate_worker_adapter,
)
from scripts.run_instance4_autoprompt_guardrails import build_instance4_artifact


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_fresh_inputs(root: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _write_json(
        root / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": now,
            "agent_run_mode": "live",
            "execution_mode": "live",
            "allow_order_submission": True,
            "summary": {"launch_posture": "clear"},
        },
    )
    _write_json(
        root / "reports" / "finance" / "latest.json",
        {
            "generated_at": now,
            "finance_gate_pass": True,
            "finance_gate": {"pass": True, "status": "pass", "reason": "queue_ready"},
        },
    )
    _write_json(
        root / "reports" / "root_test_status.json",
        {
            "generated_at": now,
            "summary": {"passed": 1723, "warnings": 5},
        },
    )


def test_worker_adapter_contract_exposes_first_class_adapters_and_restricted_seat_bridge() -> None:
    contract = build_worker_adapter_contract()

    adapters = contract["first_class_adapters"]
    assert set(adapters.keys()) == {
        "codex_local",
        "claude_code_cli",
        "openai_api",
        "anthropic_api",
    }

    seat_bridge = contract["restricted_adapters"]["browser_seat_bridge"]
    assert seat_bridge["enabled"] is False
    assert seat_bridge["allowed_tiers"] == [1, 2]
    assert seat_bridge["allowed_lane_classes"] == ["research", "docs"]


def test_evaluate_worker_adapter_blocks_seat_bridge_on_tier3_trading_lane() -> None:
    result = evaluate_worker_adapter(
        adapter="browser_seat_bridge",
        lane_name="fast-trading-worker",
        changed_paths=["bot/jj_live.py"],
        seat_bridge_enabled=False,
    )

    assert result["allowed"] is False
    assert "seat_bridge_disabled_by_default" in result["reasons"]
    assert "seat_bridge_tier_restricted" in result["reasons"]
    assert "seat_bridge_lane_restricted" in result["reasons"]


def test_merge_decision_auto_merges_tier2_and_gates_tier3() -> None:
    tier2 = build_merge_decision(
        changed_paths=["scripts/run_instance4_autoprompt_guardrails.py"],
        adapter_allowed=True,
        tests_pass=True,
        artifact_contract_pass=True,
        policy_boundary_pass=True,
        no_risk_delta_pass=True,
        judge_approved=True,
    )
    assert tier2["merge_class"] == "auto_merge"
    assert tier2["decision"] == "merge_now"

    tier3 = build_merge_decision(
        changed_paths=["bot/jj_live.py"],
        adapter_allowed=True,
        tests_pass=True,
        artifact_contract_pass=True,
        policy_boundary_pass=True,
        no_risk_delta_pass=False,
        judge_approved=True,
    )
    assert tier3["merge_class"] == "no_merge"
    assert tier3["decision"] == "hold_for_human"
    assert "no_risk_delta_failed" in tier3["missing_requirements"]


def test_provider_boundary_keeps_openclaw_and_supervisors_non_governing() -> None:
    payload = build_provider_boundary_matrix()
    assert payload["openclaw"]["mode"] == "comparison_only"
    assert payload["openclaw"]["governance_authority"] is False

    supervisors = payload["hermes_like_supervisors"]
    assert supervisors["merge_authority"] is False
    assert supervisors["truth_precedence"] is False
    assert supervisors["live_risk_policy"] is False
    assert supervisors["treasury_policy"] is False


def test_build_instance4_artifact_matches_required_outputs_contract(tmp_path: Path) -> None:
    _write_fresh_inputs(tmp_path)

    artifact = build_instance4_artifact(tmp_path)

    required = artifact["required_outputs"]
    assert required["candidate_delta_arr_bps"] == 130
    assert required["expected_improvement_velocity_delta"] == 0.12
    assert required["arr_confidence_score"] == 0.74
    assert required["block_reasons"] == ["no_merge_authority_matrix", "no_provider_adapter_contract"]
    assert required["finance_gate_pass"] is True
    assert required["one_next_cycle_action"] == "activate judge_verdict.v1 before any autonomous merge"

    assert artifact["stale_hold_repair"]["active"] is False
    assert artifact["contracts"] == {
        "worker_adapter": "worker_adapter.v1",
        "judge_verdict": "judge_verdict.v1",
        "merge_decision": "merge_decision.v1",
    }


def test_build_instance4_artifact_sets_hold_repair_when_critical_inputs_missing(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {"generated_at": datetime.now(timezone.utc).isoformat(), "finance_gate_pass": True},
    )

    artifact = build_instance4_artifact(tmp_path)
    hold_repair = artifact["stale_hold_repair"]

    assert hold_repair["active"] is True
    assert hold_repair["mode"] == "observe_only"
    assert hold_repair["retry_in_minutes"] == 15
    assert any(str(reason).startswith("missing:reports/runtime_truth_latest.json") for reason in hold_repair["block_reasons"])
    assert any(str(reason).startswith("missing:reports/root_test_status.json") for reason in hold_repair["block_reasons"])
