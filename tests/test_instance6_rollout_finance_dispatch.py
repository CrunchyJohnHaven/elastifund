from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.run_instance6_rollout_finance_dispatch import build_instance6_dispatch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _base_runtime_truth(*, allow_order_submission: bool, stage_label: str, score: float = 0.71) -> dict:
    return {
        "allow_order_submission": allow_order_submission,
        "summary": {
            "launch_posture": "clear" if allow_order_submission else "blocked",
            "btc5_allowed_stage": stage_label,
        },
        "deployment_confidence": {
            "overall_score": score,
        },
        "btc_5min_maker": {
            "status": "ok",
            "live_filled_rows": 140,
        },
        "btc5_selected_package": {
            "median_arr_delta_pct": 25.0,
        },
    }


def _base_state_improvement(*, conversion: float, notional: float, max_position: float = 5.0) -> dict:
    return {
        "active_thresholds": {
            "max_position_usd": max_position,
        },
        "metrics": {
            "candidate_to_trade_conversion": conversion,
        },
        "per_venue_executed_notional_usd": {
            "combined_hourly": notional,
        },
        "improvement_velocity": {
            "deltas": {
                "candidate_to_trade_conversion_delta": 0.03,
            }
        },
    }


def _base_finance_latest(finance_gate_pass: bool = True) -> dict:
    return {
        "finance_gate_pass": finance_gate_pass,
        "finance_gate": {
            "pass": finance_gate_pass,
            "status": "pass" if finance_gate_pass else "hold",
            "reason": "queue_ready" if finance_gate_pass else "destination_not_whitelisted",
        },
    }


def _base_model_budget_plan() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_outputs": {
            "block_reasons": [
                "llm_budget_not_queued",
                "trading_treasury_expansion_blocked_but_research_spend_not_split",
            ],
            "one_next_cycle_action": "queue the pilot model-budget package under the finance caps",
        },
        "queue_package": {
            "operating_point": "pilot",
            "status": "queued",
            "monthly_total_usd": 200.0,
            "policy_compliant": True,
        },
        "operating_points": [
            {"operating_point": "pilot", "monthly_budget_usd": 200.0, "recommended_now": True},
            {"operating_point": "active", "monthly_budget_usd": 400.0, "recommended_now": False},
            {"operating_point": "max", "monthly_budget_usd": 800.0, "recommended_now": False},
        ],
    }


def _write_fresh_cross_asset_artifacts(root: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _write_json(
        root / "reports" / "data_plane_health" / "latest.json",
        {
            "generated_at": now,
            "metrics": {
                "sequence_gap_count": 0,
                "book_staleness_breach_count": 0,
                "feed_disagreement_count": 0,
            },
        },
    )
    _write_json(
        root / "reports" / "market_registry" / "latest.json",
        {
            "generated_at": now,
            "rows": [
                {"asset": "BTC", "staleness_seconds": 1},
                {"asset": "ETH", "staleness_seconds": 2},
                {"asset": "SOL", "staleness_seconds": 2},
                {"asset": "XRP", "staleness_seconds": 3},
                {"asset": "DOGE", "staleness_seconds": 4},
            ],
        },
    )
    _write_json(
        root / "reports" / "cross_asset_cascade" / "latest.json",
        {
            "generated_at": now,
            "trigger_score": 0.72,
        },
    )
    _write_json(
        root / "reports" / "cross_asset_mc" / "latest.json",
        {
            "generated_at": now,
            "tail_risk_breach": False,
            "drawdown_stress_breach": False,
            "correlation_collapse": False,
        },
    )


def _write_instance2_baseline(root: Path, *, baseline_live_ok: bool, baseline_status: str = "baseline_live_ok") -> None:
    _write_json(
        root / "reports" / "instance2_btc5_baseline" / "latest.json",
        {
            "baseline_contract": {
                "baseline_live_ok": baseline_live_ok,
                "baseline_status": baseline_status,
            },
            "baseline_guard": {
                "status_triplet": {
                    "baseline": baseline_status,
                    "stage_upgrade": "stage_upgrade_blocked",
                    "treasury_expansion": "treasury_expansion_blocked",
                },
                "permitted_baseline_attempts": ["maintain_stage1_flat_size"],
                "blocked_actions": ["promote_stage_1_size_or_higher"],
                "hold_repair": {"active": True, "retry_in_minutes": 10},
                "control_modes": {
                    "deploy_recommend": {
                        "allowed": True,
                        "allowed_actions": ["recommend_maintain_live_stage1_flat_size"],
                    }
                },
            },
        },
    )


def test_instance6_dispatch_blocks_with_explicit_stale_hold_retry(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        _base_runtime_truth(allow_order_submission=False, stage_label="stage_0"),
    )
    _write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        _base_state_improvement(conversion=0.0, notional=0.0),
    )
    _write_json(tmp_path / "reports" / "finance" / "latest.json", _base_finance_latest(finance_gate_pass=True))
    _write_json(tmp_path / "reports" / "finance" / "model_budget_plan.json", _base_model_budget_plan())
    _write_json(
        tmp_path / "reports" / "finance" / "action_queue.json",
        {
            "actions": [
                {
                    "action_key": "allocate::fund_nontrading",
                    "amount_usd": 12.0,
                    "monthly_commitment_usd": 0.0,
                    "priority_score": 2.0,
                    "status": "queued",
                }
            ]
        },
    )

    payload = build_instance6_dispatch(tmp_path)

    assert payload["operator_packet"]["decision"] == "block"
    assert payload["operator_packet"]["retry_in_minutes"] == 5
    assert payload["stale_hold_repair"]["active"] is True
    assert any(reason.startswith("missing:reports/data_plane_health/latest.json") for reason in payload["block_reasons"])
    assert payload["required_outputs"]["finance_gate_pass"] is True


def test_instance6_dispatch_advances_to_four_asset_basket_when_gates_green(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        _base_runtime_truth(allow_order_submission=True, stage_label="stage_2", score=0.84),
    )
    _write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        _base_state_improvement(conversion=0.22, notional=25.0),
    )
    _write_json(tmp_path / "reports" / "finance" / "latest.json", _base_finance_latest(finance_gate_pass=True))
    _write_json(tmp_path / "reports" / "finance" / "model_budget_plan.json", _base_model_budget_plan())
    _write_json(
        tmp_path / "reports" / "finance" / "action_queue.json",
        {
            "actions": [
                {
                    "action_key": "allocate::fund_trading",
                    "amount_usd": 50.0,
                    "monthly_commitment_usd": 100.0,
                    "priority_score": 10.0,
                    "status": "queued",
                    "destination": "polymarket_runtime",
                }
            ]
        },
    )
    _write_fresh_cross_asset_artifacts(tmp_path)

    payload = build_instance6_dispatch(tmp_path)

    assert payload["operator_packet"]["decision"] == "action"
    assert payload["rollout_ladder"]["active_stage_name"] == "four_asset_basket"
    assert payload["cascade_execution_guard"]["enabled"] is True
    assert payload["required_outputs"]["finance_gate_pass"] is True
    assert payload["required_outputs"]["block_reasons"] == []
    assert payload["research_tooling_budget"]["queue_package_operating_point"] == "pilot"
    assert payload["research_tooling_budget"]["queue_package_monthly_total_usd"] == 200.0


def test_instance6_dispatch_prefers_instance2_baseline_guard_when_runtime_rows_are_zero(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            **_base_runtime_truth(allow_order_submission=True, stage_label="stage_2", score=0.84),
            "btc_5min_maker": {"status": "ok", "live_filled_rows": 0},
        },
    )
    _write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        _base_state_improvement(conversion=0.22, notional=25.0),
    )
    _write_json(tmp_path / "reports" / "finance" / "latest.json", _base_finance_latest(finance_gate_pass=True))
    _write_json(tmp_path / "reports" / "finance" / "model_budget_plan.json", _base_model_budget_plan())
    _write_json(tmp_path / "reports" / "finance" / "action_queue.json", {"actions": []})
    _write_instance2_baseline(tmp_path, baseline_live_ok=True)
    _write_fresh_cross_asset_artifacts(tmp_path)

    payload = build_instance6_dispatch(tmp_path)

    assert payload["baseline_guard"]["btc5_baseline_ready"] is True
    assert payload["baseline_guard"]["baseline_status"] == "baseline_live_ok"
    assert payload["baseline_guard"]["source_path"] == "reports/instance2_btc5_baseline/latest.json"
    assert payload["baseline_guard"]["permitted_baseline_attempts"] == ["maintain_stage1_flat_size"]


def test_instance6_dispatch_blocks_when_single_action_cap_is_exceeded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JJ_FINANCE_SINGLE_ACTION_CAP_USD", "250")
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        _base_runtime_truth(allow_order_submission=True, stage_label="stage_2"),
    )
    _write_json(
        tmp_path / "reports" / "state_improvement_latest.json",
        _base_state_improvement(conversion=0.10, notional=5.0),
    )
    _write_json(tmp_path / "reports" / "finance" / "latest.json", _base_finance_latest(finance_gate_pass=True))
    _write_json(tmp_path / "reports" / "finance" / "model_budget_plan.json", _base_model_budget_plan())
    _write_json(
        tmp_path / "reports" / "finance" / "action_queue.json",
        {
            "actions": [
                {
                    "action_key": "allocate::oversized_vendor",
                    "amount_usd": 500.0,
                    "monthly_commitment_usd": 0.0,
                    "priority_score": 50.0,
                    "status": "queued",
                }
            ]
        },
    )
    _write_fresh_cross_asset_artifacts(tmp_path)

    payload = build_instance6_dispatch(tmp_path)

    assert payload["operator_packet"]["decision"] == "block"
    assert payload["required_outputs"]["finance_gate_pass"] is False
    assert any(reason.startswith("single_action_cap_exceeded:") for reason in payload["required_outputs"]["block_reasons"])
