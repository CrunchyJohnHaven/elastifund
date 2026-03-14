from __future__ import annotations

from pathlib import Path

from scripts.run_btc5_autoresearch_cycle import (
    _build_package_ranking,
    _package_class_summary,
    _capital_stage_recommendation,
    _build_hypothesis_candidate,
    _capital_scale_recommendation,
    _current_probe_payload_fields,
    _deploy_recommendation,
    _execution_drag_context,
    _fund_reconciliation_blocked,
    _live_fill_windows,
    _one_sided_bias_recommendation,
    _probe_feedback_adjustment,
    _package_freeze_contract,
    _rank_candidate_packages,
    _select_runtime_payload,
    _select_public_forecast,
    _selected_runtime_contract,
    _size_aware_deployment_summary,
    _runtime_session_policy_from_overrides,
    _load_env_file,
    _merged_strategy_env,
    _profile_from_env,
    _probe_gated_decision,
    _promotion_decision,
    _write_reports,
    render_strategy_env,
)
from scripts.btc5_policy_benchmark import runtime_package_hash


def test_load_env_file_parses_comments_and_values(tmp_path: Path) -> None:
    path = tmp_path / "base.env"
    path.write_text("# comment\nBTC5_MAX_ABS_DELTA=0.00015\nBTC5_UP_MAX_BUY_PRICE='0.49'\n")
    values = _load_env_file(path)
    assert values["BTC5_MAX_ABS_DELTA"] == "0.00015"
    assert values["BTC5_UP_MAX_BUY_PRICE"] == "0.49"


def test_merged_strategy_env_prefers_override(tmp_path: Path) -> None:
    base = tmp_path / "base.env"
    override = tmp_path / "override.env"
    base.write_text("BTC5_UP_MAX_BUY_PRICE=0.49\nBTC5_DOWN_MAX_BUY_PRICE=0.51\n")
    override.write_text("BTC5_UP_MAX_BUY_PRICE=0.48\n")
    merged = _merged_strategy_env(base, override)
    assert merged["BTC5_UP_MAX_BUY_PRICE"] == "0.48"
    assert merged["BTC5_DOWN_MAX_BUY_PRICE"] == "0.51"


def test_profile_from_env_builds_guardrail_profile() -> None:
    profile = _profile_from_env(
        "current_live_profile",
        {
            "BTC5_MAX_ABS_DELTA": "0.00015",
            "BTC5_UP_MAX_BUY_PRICE": "0.49",
            "BTC5_DOWN_MAX_BUY_PRICE": "0.51",
        },
    )
    assert profile.name == "current_live_profile"
    assert profile.max_abs_delta == 0.00015
    assert profile.up_max_buy_price == 0.49
    assert profile.down_max_buy_price == 0.51


def test_promotion_decision_holds_when_current_is_best() -> None:
    current = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 40.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 45.0, "profit_probability": 0.96, "p95_max_drawdown_usd": 20.0, "loss_limit_hit_probability": 0.1},
        "continuation": {"historical_arr_pct": 1000.0, "median_arr_pct": 1200.0, "p05_arr_pct": 300.0},
    }
    decision = _promotion_decision(
        best=current,
        current=current,
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )
    assert decision["action"] == "hold"
    assert decision["reason"] == "current_profile_is_best"


def test_promotion_decision_promotes_only_when_gates_pass() -> None:
    best = {
        "profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "base_profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 44.0, "replay_live_filled_rows": 24},
        "monte_carlo": {"median_total_pnl_usd": 52.0, "profit_probability": 0.965, "p95_max_drawdown_usd": 22.0, "loss_limit_hit_probability": 0.11},
        "continuation": {"historical_arr_pct": 1500.0, "median_arr_pct": 1700.0, "p05_arr_pct": 400.0},
    }
    current = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 40.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 49.0, "profit_probability": 0.96, "p95_max_drawdown_usd": 20.0, "loss_limit_hit_probability": 0.10},
        "continuation": {"historical_arr_pct": 1200.0, "median_arr_pct": 1400.0, "p05_arr_pct": 350.0},
    }
    decision = _promotion_decision(
        best=best,
        current=current,
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )
    assert decision["action"] == "promote"
    assert decision["policy_loss_delta"] > 0.0


def test_promotion_decision_holds_when_policy_loss_does_not_improve() -> None:
    best = {
        "profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "base_profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 44.0, "replay_live_filled_rows": 24},
        "monte_carlo": {"median_total_pnl_usd": 55.0, "profit_probability": 0.60, "p95_max_drawdown_usd": 60.0, "loss_limit_hit_probability": 0.45},
        "continuation": {"historical_arr_pct": 1300.0, "median_arr_pct": 1800.0, "p05_arr_pct": 380.0},
    }
    current = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 40.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 49.0, "profit_probability": 0.96, "p95_max_drawdown_usd": 20.0, "loss_limit_hit_probability": 0.10},
        "continuation": {"historical_arr_pct": 1200.0, "median_arr_pct": 1400.0, "p05_arr_pct": 350.0},
    }
    decision = _promotion_decision(
        best=best,
        current=current,
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )
    assert decision["action"] == "hold"
    assert decision["policy_loss_delta"] > 0.0
    assert "profit_probability_drop_too_large" in decision["reason"]
    assert "drawdown_increase_too_large" in decision["reason"]
    assert "loss_hit_increase_too_large" in decision["reason"]


def test_promotion_decision_treats_session_policy_as_distinct_target() -> None:
    best = {
        "profile": {"name": "policy_current_live_profile__hour_et_09", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [
            {
                "session_name": "hour_et_09",
                "et_hours": [9],
                "profile": {"name": "grid_d0.00010_up0.48_down0.49", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
            }
        ],
        "historical": {"replay_live_filled_pnl_usd": 44.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 52.0, "profit_probability": 0.962, "p95_max_drawdown_usd": 18.0, "loss_limit_hit_probability": 0.08},
        "continuation": {"historical_arr_pct": 1400.0, "median_arr_pct": 1800.0, "p05_arr_pct": 420.0},
    }
    current = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 40.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 49.0, "profit_probability": 0.96, "p95_max_drawdown_usd": 20.0, "loss_limit_hit_probability": 0.10},
        "continuation": {"historical_arr_pct": 1200.0, "median_arr_pct": 1400.0, "p05_arr_pct": 350.0},
    }

    decision = _promotion_decision(
        best=best,
        current=current,
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )

    assert decision["action"] == "promote"


def test_promotion_decision_allows_small_fill_drop_when_retention_is_high() -> None:
    best = {
        "profile": {"name": "policy_current_live_profile__hour_et_09", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [
            {
                "session_name": "hour_et_09",
                "et_hours": [9],
                "profile": {"name": "grid_d0.00010_up0.48_down0.49", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
            }
        ],
        "historical": {"replay_live_filled_pnl_usd": 44.0, "replay_live_filled_rows": 18},
        "monte_carlo": {"median_total_pnl_usd": 52.0, "profit_probability": 0.962, "p95_max_drawdown_usd": 18.0, "loss_limit_hit_probability": 0.08},
        "continuation": {"historical_arr_pct": 1400.0, "median_arr_pct": 1800.0, "p05_arr_pct": 420.0},
    }
    current = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 40.0, "replay_live_filled_rows": 20},
        "monte_carlo": {"median_total_pnl_usd": 49.0, "profit_probability": 0.96, "p95_max_drawdown_usd": 20.0, "loss_limit_hit_probability": 0.10},
        "continuation": {"historical_arr_pct": 1200.0, "median_arr_pct": 1400.0, "p05_arr_pct": 350.0},
    }

    decision = _promotion_decision(
        best=best,
        current=current,
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )

    assert decision["action"] == "promote"
    assert decision["fill_lift"] == -2
    assert decision["fill_retention_ratio"] == 0.9


def test_render_override_env_contains_promoted_values_and_session_overrides() -> None:
    text = render_strategy_env(
        {
            "profile": {"name": "policy_current_live_profile__hour_et_09", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
            "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.50},
            "session_overrides": [
                {
                    "session_name": "hour_et_09",
                    "et_hours": [9],
                    "profile": {"name": "grid_d0.00010_up0.48_down0.49", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
                }
            ],
        },
        {"generated_at": "2026-03-09T18:30:00Z", "reason": "promotion_thresholds_met"},
    )
    assert "BTC5_MAX_ABS_DELTA=0.0001" in text
    assert "BTC5_UP_MAX_BUY_PRICE=0.48" in text
    assert "BTC5_PROBE_DOWN_MAX_BUY_PRICE=0.5" in text
    assert '# candidate=policy_current_live_profile__hour_et_09' in text
    assert 'BTC5_SESSION_OVERRIDES_JSON=[{"session_name":"hour_et_09"' in text
    assert 'BTC5_SESSION_POLICY_JSON=[{"name":"hour_et_09"' in text


def test_render_override_env_lowers_min_buy_price_when_current_floor_conflicts() -> None:
    text = render_strategy_env(
        {
            "profile": {
                "name": "active_profile",
                "max_abs_delta": 0.00015,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            },
            "session_overrides": [],
        },
        {
            "generated_at": "2026-03-12T01:50:00Z",
            "reason": "frontier_policy_loss",
            "current_min_buy_price": "0.50",
        },
    )

    assert "BTC5_MIN_BUY_PRICE=0.49" in text


def test_write_reports_keeps_artifacts_in_both_json_outputs(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-03-09T18:30:00Z",
        "decision": {
            "action": "hold",
            "reason": "current_profile_is_best",
            "lab_action": "promote",
            "lab_reason": "promotion_thresholds_met",
            "probe_gate_applied": True,
            "probe_gate_reason_tags": ["trailing_12_live_filled_non_positive"],
            "median_arr_delta_pct": 0.0,
            "historical_arr_delta_pct": 0.0,
            "p05_arr_delta_pct": 0.0,
        },
        "active_profile": {"name": "current_live_profile"},
        "best_candidate": {"profile": {"name": "current_live_profile"}},
        "active_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "best_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "deploy_recommendation": "hold",
        "package_confidence_label": "low",
        "package_confidence_reasons": ["insufficient_validation_or_generalization"],
        "package_missing_evidence": ["validation_live_filled_rows_below_6"],
        "validation_live_filled_rows": 0,
        "generalization_ratio": 0.0,
        "runtime_load_status": {
            "override_env_written": True,
            "override_env_path": "state/btc5_autoresearch.env",
            "session_policy_records": 2,
            "base_env_changed": False,
            "service_restart_requested": False,
            "service_restart_state": None,
        },
        "size_aware_deployment": {
            "available": True,
            "capacity_profile_label": "best_candidate",
            "capacity_profile_name": "best_candidate_profile",
            "match_reason": "exact_global_best_candidate_match",
            "recommended_live_stage_cap": 2,
            "recommended_live_trade_size_cap_usd": 20,
        },
        "capital_scale_recommendation": {
            "status": "test_add",
            "recommended_tranche_usd": 100,
            "reason": "high_confidence_and_trailing12_positive_but_fund_reconciliation_blocks_full_scale",
        },
        "capital_stage_recommendation": {
            "recommended_stage": 2,
            "recommended_max_trade_usd": 20,
            "stage_reason": "stage2_guardrails_passed_trailing40_12_positive_and_order_failure_below_25pct",
            "promotion_guardrails_passed": True,
        },
        "package_ranking": {
            "class_breakdown": {"promote": 0, "hold_current": 1, "probe_only": 0, "suppress_cluster": 0},
            "package_set_breakdown": {"live_candidate": 0, "shadow_only": 0, "hold_current": 1, "suppress": 0},
            "top_package_set": "hold_current",
            "ranked_packages": [
                {
                    "rank": 1,
                    "profile_name": "current_live_profile",
                    "effective_candidate_class": "hold_current",
                    "effective_package_set": "hold_current",
                    "probe_aware_live_score": 12.5,
                }
            ],
        },
        "simulation_summary": {"input": {"observed_window_rows": 75, "live_filled_rows": 45}},
    }
    artifacts = _write_reports(tmp_path, payload)
    cycle_text = Path(artifacts["cycle_json"]).read_text()
    latest_text = Path(artifacts["latest_json"]).read_text()
    latest_md = Path(artifacts["latest_md"]).read_text()
    assert '"artifacts"' in cycle_text
    assert '"artifacts"' in latest_text
    assert '"runtime_load_status"' in latest_text
    assert '"size_aware_deployment"' in latest_text
    assert '"capital_stage_recommendation"' in latest_text
    assert '"package_ranking"' in latest_text
    assert '"package_set_breakdown"' in latest_text
    assert "Runtime Load Status" in latest_md
    assert "Size-Aware Deployment" in latest_md
    assert "Override env written" in latest_md
    assert "Capital stage recommendation" in latest_md
    assert "Package Ranking" in latest_md
    assert "Probe gate applied" in latest_md
    assert "Live-candidate count" in latest_md
    assert "Top package set" in latest_md


def test_deploy_recommendation_promote_shadow_hold() -> None:
    decision = {
        "median_arr_delta_pct": 0.2,
        "policy_loss_delta": 0.3,
        "profit_probability_delta": 0.0,
        "p95_drawdown_delta_usd": 1.0,
    }
    assert (
        _deploy_recommendation(
            decision_action="promote",
            decision=decision,
            validation_live_filled_rows=3,
            generalization_ratio=0.1,
        )
        == "promote"
    )
    assert (
        _deploy_recommendation(
            decision_action="hold",
            decision=decision,
            validation_live_filled_rows=6,
            generalization_ratio=0.8,
        )
        == "shadow_only"
    )
    assert (
        _deploy_recommendation(
            decision_action="hold",
            decision={"median_arr_delta_pct": 0.0, "policy_loss_delta": 0.0, "profit_probability_delta": 0.0, "p95_drawdown_delta_usd": 1.0},
            validation_live_filled_rows=10,
            generalization_ratio=0.9,
        )
        == "hold"
    )


def test_select_public_forecast_prefers_confidence_then_deploy_then_recency() -> None:
    standard = {
        "generated_at": "2026-03-10T11:00:00+00:00",
        "arr_tracking": {
            "current_median_arr_pct": 100.0,
            "best_median_arr_pct": 140.0,
            "median_arr_delta_pct": 40.0,
        },
        "package_confidence_label": "medium",
        "deploy_recommendation": "promote",
        "best_runtime_package": {"profile": {"name": "standard_best"}, "session_policy": []},
        "active_runtime_package": {"profile": {"name": "standard_active"}, "session_policy": []},
        "validation_live_filled_rows": 10,
        "generalization_ratio": 0.8,
        "runtime_load_status": {"override_env_written": True},
        "capital_stage_recommendation": {"recommended_stage": 1},
        "best_live_package": {"source": "global_best_candidate"},
        "execution_drag_summary": {"order_failed_count": 1},
        "size_aware_deployment": {"available": True, "recommended_live_stage_cap": 1},
    }
    probe = {
        "generated_at": "2026-03-10T11:30:00+00:00",
        "arr_tracking": {
            "current_median_arr_pct": 100.0,
            "best_median_arr_pct": 130.0,
            "median_arr_delta_pct": 30.0,
        },
        "package_confidence_label": "high",
        "deploy_recommendation": "hold",
        "best_runtime_package": {"profile": {"name": "probe_best"}, "session_policy": [{"name": "open_et", "et_hours": [9]}]},
        "active_runtime_package": {"profile": {"name": "probe_active"}, "session_policy": []},
        "validation_live_filled_rows": 12,
        "generalization_ratio": 0.9,
        "runtime_load_status": {"override_env_written": False},
        "capital_stage_recommendation": {"recommended_stage": 2},
        "best_live_package": {"source": "probe_candidate"},
        "execution_drag_summary": {"order_failed_count": 0},
        "size_aware_deployment": {"available": True, "recommended_live_stage_cap": 2},
    }

    selected = _select_public_forecast(
        standard_payload=standard,
        current_probe_payload=probe,
        standard_source="reports/btc5_autoresearch/latest.json",
        current_probe_source="reports/btc5_autoresearch_current_probe/latest.json",
    )
    chosen = selected["selected"]
    assert chosen["source_artifact"] == "reports/btc5_autoresearch_current_probe/latest.json"
    assert chosen["package_confidence_label"] == "high"
    assert chosen["runtime_load_status"]["override_env_written"] is False
    assert chosen["capital_stage_recommendation"]["recommended_stage"] == 2
    assert chosen["best_live_package"]["source"] == "probe_candidate"
    assert chosen["execution_drag_summary"]["order_failed_count"] == 0
    assert chosen["size_aware_deployment"]["recommended_live_stage_cap"] == 2
    assert selected["selection_reason"].endswith("with_probe_feedback")


def test_package_freeze_contract_exposes_one_live_package_and_one_shadow_comparator() -> None:
    canonical_live = {
        "profile": {
            "name": "active_profile_probe_d0_00075",
            "max_abs_delta": 0.00075,
            "up_max_buy_price": 0.49,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [],
    }
    shadow_override = {
        "profile": {
            "name": "policy_current_live_profile__hour_et_11__grid_d0.00015_up0.51_down0.51",
            "max_abs_delta": 0.00075,
            "up_max_buy_price": 0.49,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [{"name": "hour_et_11", "et_hours": [11], "max_abs_delta": 0.00015, "up_max_buy_price": 0.51, "down_max_buy_price": 0.51}],
    }
    freeze = _package_freeze_contract(
        selected_active_runtime_package=canonical_live,
        selected_best_runtime_package=canonical_live,
        best_live_package={"runtime_package": shadow_override},
        best_raw_package={"runtime_package": shadow_override},
        runtime_package_selection={"source": "standard", "source_artifact": "reports/autoresearch/btc5_policy/latest.json"},
        selected_deploy_recommendation="shadow_only",
    )

    assert freeze["canonical_live_package"]["policy_id"] == "active_profile_probe_d0_00075"
    assert freeze["canonical_live_package"]["status"] == "live_current"
    assert freeze["shadow_comparator_package"]["policy_id"] == (
        "policy_current_live_profile__hour_et_11__grid_d0.00015_up0.51_down0.51"
    )
    assert freeze["shadow_comparator_package"]["status"] == "shadow_only"
    assert "session_conditioned_override_shadow_only" in freeze["shadow_comparator_package"]["reason_tags"]
    assert freeze["package_consistency_status"] == "aligned_one_live_one_shadow"


def test_current_probe_contract_tracks_mix_growth_and_loss_clusters() -> None:
    rows = [
        {
            "updated_at": "2026-03-10T12:00:00+00:00",
            "window_start_ts": 1_710_072_000,
            "direction": "DOWN",
            "session_name": "open_et",
            "order_price": 0.48,
            "abs_delta": 0.00004,
            "order_status": "live_filled",
            "pnl_usd": 4.5,
        },
        {
            "updated_at": "2026-03-10T12:05:00+00:00",
            "window_start_ts": 1_710_072_300,
            "direction": "DOWN",
            "session_name": "open_et",
            "order_price": 0.48,
            "abs_delta": 0.00004,
            "order_status": "live_filled",
            "pnl_usd": -1.2,
        },
        {
            "updated_at": "2026-03-10T12:10:00+00:00",
            "window_start_ts": 1_710_072_600,
            "direction": "UP",
            "session_name": "midday_et",
            "order_price": 0.51,
            "abs_delta": 0.00011,
            "order_status": "live_order_failed",
            "pnl_usd": 0.0,
        },
    ]
    probe = _current_probe_payload_fields(
        rows=rows,
        prior_probe_payload={
            "validation_live_filled_rows": 8,
            "current_probe": {"live_filled_row_count": 1},
        },
        hypothesis_summary={},
        regime_policy_summary={
            "loss_cluster_filters": [
                {
                    "filter_name": "down_open_lt_0.49_le_0.00005",
                    "direction": "DOWN",
                    "session_name": "open_et",
                    "price_bucket": "lt_0.49",
                    "delta_bucket": "le_0.00005",
                    "severity": "high",
                    "filter_action": "shadow_block_until_revalidated",
                    "revalidation_gate": "requires_fresh_positive_cluster_and_capacity_agreement",
                }
            ]
        },
        validation_live_filled_rows=10,
        package_missing_evidence=[],
        decision={"action": "promote"},
    )

    assert probe["validation_live_filled_rows_delta"] == 2
    assert probe["live_filled_rows_delta"] == 1
    assert probe["recent_order_failed_rate"] > 0.0
    assert probe["recent_direction_mix"]["dominant_label"] == "DOWN"
    assert probe["recent_price_bucket_mix"]["dominant_label"] == "lt_0.49"
    assert probe["recent_loss_cluster_flags"][0]["filter_name"] == "down_open_lt_0.49_le_0.00005"
    assert probe["trailing_12_live_filled_rows"] == 2
    assert probe["ranking_inputs"]["trailing_fill_counts"]["trailing_12"] == 2
    assert probe["ranking_inputs"]["recent_order_failed_rate"] > 0.0
    assert "validation_rows_growing" in probe["ranking_reasons"]
    assert "candidate_scoring_promote_ready" in probe["stage_ready_reason_tags"]
    assert "recent_loss_cluster_flags_present" in probe["stage_not_ready_reason_tags"]


def test_probe_feedback_adjustment_reduces_confidence_for_stale_probe() -> None:
    feedback = _probe_feedback_adjustment(
        package_confidence_label="high",
        deploy_recommendation="promote",
        current_probe={
            "probe_freshness_hours": 14.0,
            "live_fill_freshness_hours": 14.0,
            "validation_live_filled_rows_delta": 0,
            "live_filled_rows_delta": 0,
            "recent_order_failed_rate": 0.41,
            "recent_loss_cluster_flags": [{"filter_name": "open_cluster"}],
            "stage_not_ready_reason_tags": ["trailing_12_live_filled_non_positive"],
        },
    )

    assert feedback["effective_package_confidence_label"] == "low"
    assert feedback["effective_deploy_recommendation"] == "hold"
    assert "probe_stale_gt_12h" in feedback["adjustment_reasons"]
    assert "validation_rows_flat" in feedback["adjustment_reasons"]


def test_probe_gated_decision_blocks_promotion_when_fresh_probe_turns_negative() -> None:
    decision = _probe_gated_decision(
        decision={
            "action": "promote",
            "reason": "promotion_thresholds_met",
            "selected_source": "regime_best_candidate",
        },
        current_probe={
            "probe_freshness_hours": 0.5,
            "live_fill_freshness_hours": 0.5,
            "stage_not_ready_reason_tags": [
                "trailing_12_live_filled_non_positive",
                "validation_rows_flat",
            ],
            "ranking_inputs": {"ranking_score": -28.0},
        },
    )

    assert decision["action"] == "hold"
    assert decision["reason"] == "probe_feedback_blocks_promotion"
    assert decision["lab_action"] == "promote"
    assert decision["lab_reason"] == "promotion_thresholds_met"
    assert decision["probe_gate_applied"] is True
    assert "trailing_12_live_filled_non_positive" in decision["probe_gate_reason_tags"]
    assert "probe_ranking_negative" in decision["probe_gate_reason_tags"]


def test_build_package_ranking_assigns_effective_classes_from_probe_feedback() -> None:
    ranking = _build_package_ranking(
        ranked_packages=[
            {
                "source": "active_profile",
                "candidate_family": "global_profile",
                "runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
                "candidate_class": None,
                "candidate_class_reason_tags": [],
                "evidence_band": "validated",
                "validation_live_filled_rows": 120,
                "generalization_ratio": 1.0,
                "fill_retention_ratio": 1.0,
                "execution_realism_score": 1.0,
                "raw_research_score": 5.0,
                "live_execution_score": 10.0,
            },
            {
                "source": "regime_best_candidate",
                "candidate_family": "regime_policy",
                "runtime_package": {"profile": {"name": "policy_open"}, "session_policy": [{"name": "open_et"}]},
                "candidate_class": "promote",
                "candidate_class_reason_tags": ["validated_clear_upgrade"],
                "evidence_band": "validated",
                "validation_live_filled_rows": 123,
                "generalization_ratio": 1.02,
                "fill_retention_ratio": 0.94,
                "execution_realism_score": 0.98,
                "raw_research_score": 120.0,
                "live_execution_score": 110.0,
            },
            {
                "source": "hypothesis_best_candidate",
                "candidate_family": "hypothesis",
                "runtime_package": {"profile": {"name": "probe_spike"}, "session_policy": []},
                "candidate_class": "probe_only",
                "candidate_class_reason_tags": ["requires_revalidation"],
                "evidence_band": "exploratory",
                "validation_live_filled_rows": 5,
                "generalization_ratio": 0.42,
                "fill_retention_ratio": 0.12,
                "execution_realism_score": 0.4,
                "raw_research_score": 200.0,
                "live_execution_score": 140.0,
            },
        ],
        current_probe={
            "probe_freshness_hours": 0.5,
            "live_fill_freshness_hours": 0.5,
            "stage_not_ready_reason_tags": [
                "trailing_12_live_filled_non_positive",
                "validation_rows_flat",
            ],
            "ranking_inputs": {
                "ranking_score": -22.0,
                "probe_freshness_hours": 0.5,
                "live_fill_freshness_hours": 0.5,
                "validation_live_filled_rows_delta": 0,
                "live_filled_rows_delta": 0,
                "recent_order_failed_rate": 0.12,
                "trailing_fill_counts": {"trailing_12": 12, "trailing_40": 40, "trailing_120": 120},
                "trailing_net_positive": {"trailing_12": False, "trailing_40": True, "trailing_120": True},
                "recent_direction_mix": {},
                "recent_price_bucket_mix": {},
                "recent_loss_cluster_flags": [],
                "ranking_reasons": ["trailing_12_non_positive"],
            },
        },
    )

    assert ranking["class_breakdown"]["promote"] == 0
    assert ranking["package_set_breakdown"]["live_candidate"] == 0
    assert ranking["package_set_breakdown"]["shadow_only"] == 1
    assert ranking["package_set_breakdown"]["hold_current"] == 2
    assert ranking["package_set_breakdown"]["suppress"] == 0
    assert ranking["class_breakdown"]["hold_current"] == 2
    assert ranking["class_breakdown"]["probe_only"] == 1
    ranked_by_name = {item["profile_name"]: item for item in ranking["ranked_packages"]}
    assert ranking["top_package_set"] == "hold_current"
    assert ranked_by_name["current_live_profile"]["effective_candidate_class"] == "hold_current"
    assert ranked_by_name["current_live_profile"]["effective_package_set"] == "hold_current"
    assert ranked_by_name["policy_open"]["effective_candidate_class"] == "hold_current"
    assert ranked_by_name["policy_open"]["effective_package_set"] == "hold_current"
    assert ranked_by_name["policy_open"]["effective_candidate_class_reason"] == "fresh_probe_blocks_promote"
    assert "trailing_12_live_filled_non_positive" in ranked_by_name["policy_open"]["effective_candidate_class_reason_tags"]
    assert ranked_by_name["probe_spike"]["effective_package_set"] == "shadow_only"


def test_build_package_ranking_accepts_stable_package_set_aliases() -> None:
    ranking = _build_package_ranking(
        ranked_packages=[
            {
                "source": "hypothesis_best_candidate",
                "candidate_family": "hypothesis",
                "runtime_package": {"profile": {"name": "shadow_probe"}, "session_policy": []},
                "candidate_class": "shadow_only",
                "candidate_class_reason_tags": ["requires_revalidation"],
                "evidence_band": "candidate",
                "validation_live_filled_rows": 10,
                "generalization_ratio": 0.78,
                "fill_retention_ratio": 0.44,
                "execution_realism_score": 0.62,
                "raw_research_score": 24.0,
                "live_execution_score": 18.0,
            }
        ],
        current_probe={
            "probe_freshness_hours": 0.5,
            "live_fill_freshness_hours": 0.5,
            "stage_not_ready_reason_tags": [],
            "ranking_inputs": {
                "ranking_score": 8.0,
                "probe_freshness_hours": 0.5,
                "live_fill_freshness_hours": 0.5,
                "validation_live_filled_rows_delta": 1,
                "live_filled_rows_delta": 1,
                "recent_order_failed_rate": 0.1,
                "trailing_fill_counts": {"trailing_12": 12, "trailing_40": 40, "trailing_120": 120},
                "trailing_net_positive": {"trailing_12": True, "trailing_40": True, "trailing_120": True},
                "recent_direction_mix": {},
                "recent_price_bucket_mix": {},
                "recent_loss_cluster_flags": [],
                "ranking_reasons": ["validation_rows_growing"],
            },
        },
    )

    item = ranking["ranked_packages"][0]
    assert item["base_candidate_class"] == "probe_only"
    assert item["base_package_set"] == "shadow_only"
    assert item["effective_candidate_class"] == "probe_only"
    assert item["effective_package_set"] == "shadow_only"
    assert ranking["package_set_breakdown"]["shadow_only"] == 1


def test_build_package_ranking_demotes_hold_current_when_probe_regression_is_severe() -> None:
    ranking = _build_package_ranking(
        ranked_packages=[
            {
                "source": "active_profile",
                "candidate_family": "global_profile",
                "runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
                "candidate_class": "hold_current",
                "candidate_class_reason_tags": ["validated_baseline"],
                "evidence_band": "validated",
                "validation_live_filled_rows": 123,
                "generalization_ratio": 1.01,
                "fill_retention_ratio": 1.0,
                "execution_realism_score": 0.98,
                "raw_research_score": 14.0,
                "live_execution_score": 11.0,
            }
        ],
        current_probe={
            "probe_freshness_hours": 0.25,
            "live_fill_freshness_hours": 0.25,
            "stage_not_ready_reason_tags": [
                "trailing_12_live_filled_non_positive",
                "trailing_40_live_filled_non_positive",
                "validation_rows_flat",
            ],
            "ranking_inputs": {
                "ranking_score": -28.0,
                "probe_freshness_hours": 0.25,
                "live_fill_freshness_hours": 0.25,
                "validation_live_filled_rows_delta": 0,
                "live_filled_rows_delta": 1,
                "recent_order_failed_rate": 0.12,
                "trailing_fill_counts": {"trailing_12": 12, "trailing_40": 40, "trailing_120": 120},
                "trailing_net_positive": {"trailing_12": False, "trailing_40": False, "trailing_120": True},
                "recent_direction_mix": {},
                "recent_price_bucket_mix": {},
                "recent_loss_cluster_flags": [],
                "ranking_reasons": [
                    "trailing_12_non_positive",
                    "trailing_40_non_positive",
                    "validation_growth_stalled",
                ],
            },
        },
    )

    item = ranking["ranked_packages"][0]
    assert item["effective_candidate_class"] == "probe_only"
    assert item["effective_package_set"] == "shadow_only"
    assert item["effective_candidate_class_reason"] == "fresh_probe_demotes_hold_current"
    assert "fresh_probe_severe_regression" in item["effective_candidate_class_reason_tags"]


def test_package_class_summary_matches_runtime_package_signature() -> None:
    ranking = {
        "top_package_set": "hold_current",
        "ranked_packages": [
            {
                "rank": 1,
                "source": "active_profile",
                "profile_name": "current_live_profile",
                "runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
                "effective_candidate_class": "hold_current",
                "effective_candidate_class_reason": "class_retained",
                "effective_candidate_class_reason_tags": ["validated_baseline"],
                "effective_package_set": "hold_current",
            },
            {
                "rank": 2,
                "source": "regime_best_candidate",
                "profile_name": "policy_open",
                "runtime_package": {
                    "profile": {"name": "policy_open"},
                    "session_policy": [{"name": "open_et", "et_hours": [9, 10, 11]}],
                },
                "effective_candidate_class": "probe_only",
                "effective_candidate_class_reason": "fresh_probe_blocks_promote",
                "effective_candidate_class_reason_tags": ["validation_rows_flat"],
                "effective_package_set": "shadow_only",
            },
        ],
    }

    summary = _package_class_summary(
        ranking,
        {"profile": {"name": "policy_open"}, "session_policy": [{"name": "open_et", "et_hours": [9, 10, 11]}]},
    )

    assert summary["package_class"] == "shadow_only"
    assert summary["candidate_class"] == "probe_only"
    assert summary["class_reason"] == "fresh_probe_blocks_promote"
    assert summary["matched_runtime_package"] is True


def test_select_public_forecast_prefers_fresh_probe_over_stale_nominally_better_package() -> None:
    standard = {
        "generated_at": "2026-03-09T00:00:00+00:00",
        "arr_tracking": {
            "current_median_arr_pct": 100.0,
            "best_median_arr_pct": 220.0,
            "median_arr_delta_pct": 120.0,
        },
        "package_confidence_label": "high",
        "deploy_recommendation": "promote",
        "validation_live_filled_rows": 30,
        "generalization_ratio": 1.2,
    }
    probe = {
        "generated_at": "2026-03-10T12:30:00+00:00",
        "arr_tracking": {
            "current_median_arr_pct": 100.0,
            "best_median_arr_pct": 150.0,
            "median_arr_delta_pct": 50.0,
        },
        "package_confidence_label": "medium",
        "deploy_recommendation": "shadow_only",
        "validation_live_filled_rows": 14,
        "generalization_ratio": 0.92,
        "current_probe": {
            "probe_freshness_hours": 0.25,
            "validation_live_filled_rows_delta": 2,
            "live_filled_rows_delta": 1,
        },
        "probe_feedback": {
            "selection_score_bonus": 20.0,
            "selection_score_penalty": 0.0,
        },
    }

    selected = _select_public_forecast(
        standard_payload=standard,
        current_probe_payload=probe,
        standard_source="reports/btc5_autoresearch/latest.json",
        current_probe_source="reports/btc5_autoresearch_current_probe/latest.json",
    )

    assert selected["selected"]["source_artifact"] == "reports/btc5_autoresearch_current_probe/latest.json"


def test_select_runtime_payload_prefers_standard_cycle_even_when_probe_is_fresh() -> None:
    standard = {
        "deploy_recommendation": "promote",
        "package_confidence_label": "high",
        "package_confidence_reasons": ["validation_live_filled_rows=18"],
        "best_runtime_package": {"profile": {"name": "standard_best"}, "session_policy": []},
        "active_runtime_package": {"profile": {"name": "standard_active"}, "session_policy": []},
    }
    current_probe = {
        **standard,
        "deploy_recommendation": "hold",
        "package_confidence_label": "low",
        "package_confidence_reasons": [
            "validation_live_filled_rows=18",
            "probe_fresh_lte_1h",
            "validation_rows_flat",
        ],
        "current_probe": {"probe_freshness_hours": 0.5, "validation_live_filled_rows_delta": 0},
    }

    selected = _select_runtime_payload(
        standard_payload=standard,
        current_probe_payload=current_probe,
    )

    assert selected["source"] == "standard"
    assert selected["selection_reason"] == "standard_cycle_payload_frontier_authoritative_probe_advisory"
    assert selected["payload"]["deploy_recommendation"] == "promote"
    assert selected["payload"]["package_confidence_label"] == "high"


def test_select_runtime_payload_falls_back_to_standard_when_probe_is_stale() -> None:
    standard = {
        "deploy_recommendation": "shadow_only",
        "package_confidence_label": "high",
        "package_confidence_reasons": ["validation_live_filled_rows=18"],
        "best_runtime_package": {"profile": {"name": "standard_best"}, "session_policy": []},
        "active_runtime_package": {"profile": {"name": "standard_active"}, "session_policy": []},
    }
    current_probe = {
        **standard,
        "deploy_recommendation": "hold",
        "package_confidence_label": "low",
        "package_confidence_reasons": [
            "validation_live_filled_rows=18",
            "probe_stale_gt_12h",
            "validation_rows_flat",
        ],
        "current_probe": {"probe_freshness_hours": 14.0, "validation_live_filled_rows_delta": 0},
    }

    selected = _select_runtime_payload(
        standard_payload=standard,
        current_probe_payload=current_probe,
    )

    assert selected["source"] == "standard"
    assert selected["selection_reason"] == "standard_cycle_payload_used_for_runtime_selection_probe_stale"
    assert selected["payload"]["deploy_recommendation"] == "shadow_only"
    assert selected["payload"]["package_confidence_label"] == "high"


def test_build_package_ranking_prefers_frontier_best_with_bounded_probe_penalty() -> None:
    hour_11_package = {
        "profile": {
            "name": "hour_11",
            "max_abs_delta": 0.0001,
            "up_max_buy_price": 0.51,
            "down_max_buy_price": 0.50,
        },
        "session_policy": [],
    }
    active_package = {
        "profile": {
            "name": "active_profile",
            "max_abs_delta": 0.00015,
            "up_max_buy_price": 0.51,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [],
    }
    ranking = _build_package_ranking(
        ranked_packages=[
            {
                "source": "global_best_candidate",
                "candidate_family": "global_profile",
                "runtime_package": hour_11_package,
                "candidate_class": "promote",
                "candidate_class_reason_tags": ["validated_clear_upgrade"],
                "evidence_band": "validated",
                "validation_live_filled_rows": 90,
                "generalization_ratio": 1.01,
                "fill_retention_ratio": 0.95,
                "execution_realism_score": 0.96,
                "raw_research_score": 120.0,
                "live_execution_score": 105.0,
            },
            {
                "source": "active_profile",
                "candidate_family": "global_profile",
                "runtime_package": active_package,
                "candidate_class": "hold_current",
                "candidate_class_reason_tags": ["validated_baseline"],
                "evidence_band": "validated",
                "validation_live_filled_rows": 120,
                "generalization_ratio": 1.0,
                "fill_retention_ratio": 1.0,
                "execution_realism_score": 1.0,
                "raw_research_score": 90.0,
                "live_execution_score": 12.0,
            },
        ],
        current_probe={
            "probe_freshness_hours": 0.5,
            "live_fill_freshness_hours": 0.5,
            "stage_not_ready_reason_tags": ["trailing_12_live_filled_non_positive"],
            "ranking_inputs": {
                "ranking_score": -15.0,
                "probe_freshness_hours": 0.5,
                "live_fill_freshness_hours": 0.5,
                "validation_live_filled_rows_delta": 0,
                "live_filled_rows_delta": 0,
                "recent_order_failed_rate": 0.1,
                "trailing_fill_counts": {"trailing_12": 12, "trailing_40": 40, "trailing_120": 120},
                "trailing_net_positive": {"trailing_12": False, "trailing_40": True, "trailing_120": True},
                "recent_direction_mix": {},
                "recent_price_bucket_mix": {},
                "recent_loss_cluster_flags": [],
                "ranking_reasons": ["trailing_12_non_positive"],
            },
        },
        frontier_report={
            "incumbent_package_hash": runtime_package_hash(hour_11_package),
            "incumbent_policy_loss": -54143.0069,
            "best_market_package_hash": runtime_package_hash(active_package),
            "best_market_policy_loss": -55389.7504,
            "current_market_model_version": "7:market-hash",
            "ranked_policies": [
                {
                    "policy_id": "active_profile",
                    "package_hash": runtime_package_hash(active_package),
                    "policy_loss": -55389.7504,
                    "policy_components": {"policy_loss": -55389.7504},
                    "market_model_version": "7:market-hash",
                    "runtime_package": active_package,
                },
                {
                    "policy_id": "hour_11",
                    "package_hash": runtime_package_hash(hour_11_package),
                    "policy_loss": -52065.3358,
                    "policy_components": {"policy_loss": -52065.3358},
                    "market_model_version": "7:market-hash",
                    "runtime_package": hour_11_package,
                },
            ],
        },
    )

    top = ranking["ranked_packages"][0]
    assert top["profile_name"] == "active_profile"
    assert top["selection_source"] == "frontier_policy_loss"
    assert top["frontier_policy_loss"] == -55389.7504


def test_select_runtime_payload_uses_stale_probe_when_no_standard_exists() -> None:
    current_probe = {
        "deploy_recommendation": "hold",
        "package_confidence_label": "low",
        "package_confidence_reasons": [
            "probe_stale_gt_12h",
            "validation_rows_flat",
        ],
        "best_runtime_package": {"profile": {"name": "probe_best"}, "session_policy": []},
        "active_runtime_package": {"profile": {"name": "probe_active"}, "session_policy": []},
        "current_probe": {"probe_freshness_hours": 14.0, "validation_live_filled_rows_delta": 0},
    }

    selected = _select_runtime_payload(
        standard_payload=None,
        current_probe_payload=current_probe,
    )

    assert selected["source"] == "current_probe"
    assert selected["selection_reason"] == "current_probe_feedback_used_without_standard_fallback_probe_stale"
    assert selected["payload"]["deploy_recommendation"] == "hold"
    assert selected["payload"]["package_confidence_label"] == "low"


def test_selected_runtime_contract_carries_selected_fields_for_probe_artifact() -> None:
    contract = _selected_runtime_contract(
        runtime_package_selection={
            "source": "current_probe",
            "source_artifact": "reports/btc5_autoresearch_current_probe/latest.json",
            "selection_reason": "current_probe_feedback_authoritative_for_runtime_selection",
        },
        selected_best_runtime_package={
            "profile": {"name": "probe_best"},
            "session_policy": [{"name": "open_et", "et_hours": [9, 10, 11]}],
        },
        selected_active_runtime_package={
            "profile": {"name": "current_live_profile"},
            "session_policy": [],
        },
        selected_deploy_recommendation="hold",
        selected_package_confidence_label="low",
        selected_package_confidence_reasons=["validation_rows_flat", "trailing_12_non_positive"],
        selected_size_aware_deployment={"available": True, "recommended_live_stage_cap": 0},
        selected_package_class_summary={
            "package_class": "suppress",
            "candidate_class": "suppress_cluster",
            "class_reason": "fresh_probe_blocks_promote",
            "class_reason_tags": ["validation_rows_flat"],
            "rank": 1,
            "source": "package_ranking",
            "profile_name": "probe_best",
            "matched_runtime_package": False,
        },
        promoted_package_selected=False,
    )

    assert contract["runtime_package_selection"]["source"] == "current_probe"
    assert contract["selected_best_runtime_package"]["profile"]["name"] == "probe_best"
    assert contract["selected_active_runtime_package"]["profile"]["name"] == "current_live_profile"
    assert contract["selected_deploy_recommendation"] == "hold"
    assert contract["selected_package_confidence_label"] == "low"
    assert contract["selected_package_confidence_reasons"] == ["validation_rows_flat", "trailing_12_non_positive"]
    assert contract["selected_package_class"] == "suppress"
    assert contract["selected_package_class_reason_tags"] == ["validation_rows_flat"]
    assert contract["promoted_package_selected"] is False


def test_size_aware_deployment_summary_uses_exact_best_candidate_capacity_profile() -> None:
    best_candidate = {
        "profile": {"name": "best_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
        "base_profile": {"name": "best_profile", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
        "session_overrides": [],
    }
    current_candidate = {
        "profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "base_profile": {"name": "current_live_profile", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [],
    }
    simulation_summary = {
        "capacity_stress_summary": {
            "profiles": {
                "best_candidate": {
                    "profile_name": "best_profile",
                    "size_sweeps": [
                        {
                            "trade_size_usd": 10.0,
                            "expected_fill_probability": 0.72,
                            "expected_fill_retention_ratio": 0.6,
                            "expected_order_failed_probability": 0.12,
                            "expected_cancelled_unfilled_probability": 0.02,
                            "expected_post_only_retry_failure_rate": 0.14,
                            "expected_p05_arr_pct": 100.0,
                            "expected_median_arr_pct": 200.0,
                            "expected_profit_probability": 0.95,
                            "expected_loss_limit_hit_probability": 0.1,
                            "expected_p95_max_drawdown_usd": 8.0,
                        },
                        {
                            "trade_size_usd": 20.0,
                            "expected_fill_probability": 0.51,
                            "expected_fill_retention_ratio": 0.3,
                            "expected_order_failed_probability": 0.28,
                            "expected_cancelled_unfilled_probability": 0.05,
                            "expected_post_only_retry_failure_rate": 0.32,
                            "expected_p05_arr_pct": 80.0,
                            "expected_median_arr_pct": 180.0,
                            "expected_profit_probability": 0.92,
                            "expected_loss_limit_hit_probability": 0.18,
                            "expected_p95_max_drawdown_usd": 12.0,
                        },
                        {
                            "trade_size_usd": 50.0,
                            "expected_fill_probability": 0.18,
                            "expected_fill_retention_ratio": 0.1,
                            "expected_order_failed_probability": 0.63,
                            "expected_cancelled_unfilled_probability": 0.07,
                            "expected_post_only_retry_failure_rate": 0.66,
                            "expected_p05_arr_pct": -10.0,
                            "expected_median_arr_pct": 90.0,
                            "expected_profit_probability": 0.75,
                            "expected_loss_limit_hit_probability": 0.65,
                            "expected_p95_max_drawdown_usd": 25.0,
                        },
                        {
                            "trade_size_usd": 100.0,
                            "expected_fill_probability": 0.16,
                            "expected_fill_retention_ratio": 0.12,
                            "expected_order_failed_probability": 0.58,
                            "expected_cancelled_unfilled_probability": 0.08,
                            "expected_post_only_retry_failure_rate": 0.61,
                            "expected_p05_arr_pct": 15.0,
                            "expected_median_arr_pct": 120.0,
                            "expected_profit_probability": 0.66,
                            "expected_loss_limit_hit_probability": 0.55,
                            "expected_p95_max_drawdown_usd": 40.0,
                        },
                        {
                            "trade_size_usd": 300.0,
                            "expected_fill_probability": 0.05,
                            "expected_fill_retention_ratio": 0.04,
                            "expected_order_failed_probability": 0.82,
                            "expected_cancelled_unfilled_probability": 0.1,
                            "expected_post_only_retry_failure_rate": 0.88,
                            "expected_p05_arr_pct": -50.0,
                            "expected_median_arr_pct": 60.0,
                            "expected_profit_probability": 0.40,
                            "expected_loss_limit_hit_probability": 0.95,
                            "expected_p95_max_drawdown_usd": 180.0,
                        },
                    ],
                    "capital_ladder": {
                        "status": "live_stage2_ready",
                        "live_now": {
                            "safe_trade_size_usd": 20.0,
                            "safe_stage_label": "stage_2",
                            "max_live_stage": 2,
                        },
                        "next_notional_gate": {
                            "trade_size_usd": 50.0,
                            "blocking_categories": ["drawdown_tails"],
                        },
                        "live_stage_decisions": [
                            {"stage_label": "stage_1", "status": "live_ready", "deployment_class": "live"},
                            {"stage_label": "stage_2", "status": "live_ready", "deployment_class": "live"},
                            {
                                "stage_label": "stage_3",
                                "status": "blocked_live",
                                "deployment_class": "blocked",
                                "blocking_categories": ["drawdown_tails"],
                                "blocking_reasons": ["expected_p05_arr_pct_non_positive"],
                                "evidence_required": ["Improve stressed tail metrics: P05 ARR, daily-loss-hit probability, and P95 drawdown."],
                                "evidence_verdict": "true_negative_only",
                                "missing_evidence_items": [],
                                "true_negative_items": ["tail_risk_below_threshold"],
                            },
                        ],
                        "shadow_only": [
                            {
                                "trade_size_usd": 100.0,
                                "status": "shadow_ready",
                                "deployment_class": "shadow_only",
                                "gate_passed": True,
                                "evidence_verdict": "sufficient_positive_evidence",
                                "missing_evidence_items": [],
                                "true_negative_items": [],
                            },
                            {
                                "trade_size_usd": 300.0,
                                "status": "shadow_blocked",
                                "deployment_class": "blocked",
                                "gate_passed": False,
                                "blocking_categories": ["liquidity", "drawdown_tails"],
                                "blocking_reasons": ["fill_retention_ratio_below_threshold:0.0400<0.1000"],
                                "evidence_required": ["Improve fill retention at the target ticket size with session-aware concentration."],
                                "evidence_verdict": "true_negative_only",
                                "missing_evidence_items": [],
                                "true_negative_items": [
                                    "fill_retention_below_threshold",
                                    "tail_risk_below_threshold",
                                ],
                            },
                        ],
                    },
                }
            }
        }
    }

    summary = _size_aware_deployment_summary(
        candidate=best_candidate,
        simulation_summary=simulation_summary,
        current_candidate=current_candidate,
        global_best_candidate=best_candidate,
    )

    assert summary["available"] is True
    assert summary["capacity_profile_label"] == "best_candidate"
    assert summary["capital_ladder_status"] == "live_stage2_ready"
    assert summary["safe_live_trade_size_usd"] == 20
    assert summary["safe_live_stage_label"] == "stage_2"
    assert summary["next_notional_gate"]["trade_size_usd"] == 50.0
    assert summary["recommended_live_stage_cap"] == 2
    assert summary["recommended_live_trade_size_cap_usd"] == 20
    assert summary["live_stage_assessments"][0]["gate_passed"] is True
    assert summary["live_stage_assessments"][2]["gate_passed"] is False
    assert summary["live_stage_assessments"][2]["blocking_categories"] == ["drawdown_tails"]
    assert summary["live_stage_assessments"][2]["evidence_verdict"] == "true_negative_only"
    assert summary["shadow_trade_size_assessments"][0]["trade_size_usd"] == 100.0
    assert summary["shadow_trade_size_assessments"][1]["trade_size_usd"] == 300.0
    assert summary["shadow_trade_size_assessments"][1]["blocking_categories"] == ["liquidity", "drawdown_tails"]
    assert summary["shadow_trade_size_assessments"][0]["expected_order_failed_probability"] == 0.58
    assert summary["shadow_trade_size_assessments"][0]["expected_post_only_retry_failure_rate"] == 0.61
    assert summary["shadow_trade_size_assessments"][1]["evidence_verdict"] == "true_negative_only"
    assert summary["shadow_trade_size_assessments"][1]["true_negative_items"] == [
        "fill_retention_below_threshold",
        "tail_risk_below_threshold",
    ]


def test_runtime_session_policy_from_overrides_matches_contract() -> None:
    session_policy = _runtime_session_policy_from_overrides(
        [
            {
                "session_name": "open_et",
                "et_hours": [9, 10, 11],
                "profile": {
                    "name": "grid_d0.00010_up0.48_down0.49",
                    "max_abs_delta": 0.0001,
                    "up_max_buy_price": 0.48,
                    "down_max_buy_price": 0.49,
                },
            }
        ]
    )
    assert len(session_policy) == 1
    record = session_policy[0]
    assert record["name"] == "open_et"
    assert record["et_hours"] == [9, 10, 11]
    assert set(record.keys()) == {"name", "et_hours", "max_abs_delta", "up_max_buy_price", "down_max_buy_price"}


def test_runtime_session_policy_from_overrides_prefers_specific_hours_first() -> None:
    session_policy = _runtime_session_policy_from_overrides(
        [
            {
                "session_name": "open_et",
                "et_hours": [9, 10, 11],
                "profile": {
                    "name": "open_profile",
                    "max_abs_delta": 0.00005,
                    "up_max_buy_price": 0.47,
                    "down_max_buy_price": 0.48,
                },
            },
            {
                "session_name": "hour_et_09",
                "et_hours": [9],
                "profile": {
                    "name": "hour_profile",
                    "max_abs_delta": 0.0001,
                    "up_max_buy_price": 0.48,
                    "down_max_buy_price": 0.49,
                },
            },
        ]
    )

    assert [record["name"] for record in session_policy] == ["hour_et_09", "open_et"]


def test_live_fill_windows_and_capital_scale_recommendation() -> None:
    rows = []
    for idx in range(1, 21):
        rows.append(
            {
                "order_status": "live_filled",
                "window_start_ts": 1_700_000_000 + idx * 300,
                "pnl_usd": 1.0 if idx % 3 else -0.2,
            }
        )
    trailing = _live_fill_windows(rows)
    assert trailing["trailing_5"]["fills"] == 5
    assert trailing["trailing_12"]["fills"] == 12
    assert trailing["trailing_20"]["fills"] == 20
    recommendation = _capital_scale_recommendation(
        deploy_recommendation="promote",
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=True,
        fund_reconciliation_blocked=False,
        fund_block_reasons=[],
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 1, "recommended_live_trade_size_cap_usd": 10},
    )
    assert recommendation["status"] == "scale_add"
    assert recommendation["recommended_tranche_usd"] == 1000


def test_capital_scale_recommendation_test_add_when_fund_blocked() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 3.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 5.0, "hours": 3.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": -1.0, "hours": 6.0, "net_positive": False},
    }
    recommendation = _capital_scale_recommendation(
        deploy_recommendation="promote",
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=True,
        fund_reconciliation_blocked=True,
        fund_block_reasons=["accounting_reconciliation_drift"],
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 1, "recommended_live_trade_size_cap_usd": 10},
    )
    assert recommendation["status"] == "test_add"
    assert recommendation["recommended_tranche_usd"] == 100


def test_capital_scale_recommendation_can_scale_before_runtime_load_when_promote_is_selected() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 2.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 4.0, "hours": 2.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": 7.0, "hours": 5.0, "net_positive": True},
    }
    recommendation = _capital_scale_recommendation(
        deploy_recommendation="promote",
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=False,
        fund_reconciliation_blocked=False,
        fund_block_reasons=[],
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 1, "recommended_live_trade_size_cap_usd": 10},
    )
    assert recommendation["status"] == "scale_add"
    assert recommendation["runtime_load_required"] is True
    assert recommendation["reason"].endswith("runtime_load_required_before_scale_add")


def test_capital_scale_recommendation_hold_when_deploy_hold() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 2.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 4.0, "hours": 2.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": 7.0, "hours": 5.0, "net_positive": True},
    }
    recommendation = _capital_scale_recommendation(
        deploy_recommendation="hold",
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=True,
        fund_reconciliation_blocked=False,
        fund_block_reasons=[],
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 1, "recommended_live_trade_size_cap_usd": 10},
    )
    assert recommendation["status"] == "hold"
    assert recommendation["recommended_tranche_usd"] == 0
    assert recommendation["reason"] == "deploy_recommendation_hold_blocks_capital_add"


def test_capital_stage_recommendation_stage2_from_fresh_positive_fills() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 3.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 8.0, "hours": 3.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": 6.0, "hours": 6.0, "net_positive": True},
        "trailing_40": {"fills": 40, "pnl_usd": 10.0, "hours": 12.0, "net_positive": True},
        "trailing_120": {"fills": 80, "pnl_usd": 15.0, "hours": 30.0, "net_positive": True},
    }
    recommendation = _capital_stage_recommendation(
        deploy_recommendation="shadow_only",
        package_confidence_label="high",
        trailing=trailing,
        execution_drag_summary={"order_failure_rate": 0.2},
        promoted_package_selected=False,
        latest_live_fill_age_hours=1.5,
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 2, "recommended_live_trade_size_cap_usd": 20},
    )
    assert recommendation["recommended_stage"] == 2
    assert recommendation["recommended_max_trade_usd"] == 20
    assert recommendation["promotion_guardrails_passed"] is True
    assert recommendation["shadow_trade_sizes_usd"] == [100, 300]


def test_capital_stage_recommendation_stage3_requires_120_and_promote_path() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 3.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 8.0, "hours": 3.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": 6.0, "hours": 6.0, "net_positive": True},
        "trailing_40": {"fills": 40, "pnl_usd": 10.0, "hours": 12.0, "net_positive": True},
        "trailing_120": {"fills": 120, "pnl_usd": 25.0, "hours": 36.0, "net_positive": True},
    }
    recommendation = _capital_stage_recommendation(
        deploy_recommendation="promote",
        package_confidence_label="high",
        trailing=trailing,
        execution_drag_summary={"order_failure_rate": 0.1},
        promoted_package_selected=False,
        latest_live_fill_age_hours=0.5,
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 3, "recommended_live_trade_size_cap_usd": 50},
    )
    assert recommendation["recommended_stage"] == 3
    assert recommendation["recommended_max_trade_usd"] == 50
    assert recommendation["runtime_load_required"] is True
    assert recommendation["promotion_guardrails_passed"] is True


def test_capital_stage_recommendation_caps_stage_using_size_summary() -> None:
    trailing = {
        "trailing_5": {"fills": 5, "pnl_usd": 3.0, "hours": 1.0, "net_positive": True},
        "trailing_12": {"fills": 12, "pnl_usd": 8.0, "hours": 3.0, "net_positive": True},
        "trailing_20": {"fills": 20, "pnl_usd": 6.0, "hours": 6.0, "net_positive": True},
        "trailing_40": {"fills": 40, "pnl_usd": 10.0, "hours": 12.0, "net_positive": True},
        "trailing_120": {"fills": 120, "pnl_usd": 25.0, "hours": 36.0, "net_positive": True},
    }
    recommendation = _capital_stage_recommendation(
        deploy_recommendation="promote",
        package_confidence_label="high",
        trailing=trailing,
        execution_drag_summary={"order_failure_rate": 0.1},
        promoted_package_selected=True,
        latest_live_fill_age_hours=0.5,
        size_aware_deployment={"available": True, "recommended_live_stage_cap": 2, "recommended_live_trade_size_cap_usd": 20},
    )
    assert recommendation["recommended_stage"] == 2
    assert recommendation["recommended_max_trade_usd"] == 20
    assert recommendation["stage_reason"].endswith("size_aware_stage_cap_2")


def test_fund_reconciliation_blocked_reads_runtime_truth_checks() -> None:
    blocked, reasons = _fund_reconciliation_blocked(
        {"launch": {"blocked_checks": ["accounting_reconciliation_drift", "other"]}}
    )
    assert blocked is True
    assert reasons == ["accounting_reconciliation_drift"]


def test_execution_drag_context_counts_core_statuses() -> None:
    rows = [
        {"order_status": "skip_price_outside_guardrails", "direction": "UP"},
        {"order_status": "live_order_failed", "direction": "UP"},
        {"order_status": "live_cancelled_unfilled", "direction": "DOWN"},
        {"order_status": "live_filled", "direction": "DOWN", "pnl_usd": 2.5},
    ]
    summary = _execution_drag_context(rows)
    assert summary["skip_price_count"] == 1
    assert summary["order_failed_count"] == 1
    assert summary["cancelled_unfilled_count"] == 1
    assert summary["direction_stats"]["DOWN"]["filled_pnl_usd"] == 2.5


def test_rank_candidate_packages_prefers_live_execution_when_raw_winner_drops_fills() -> None:
    active = {
        "candidate_family": "global_profile",
        "profile": {"name": "active", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "historical": {"replay_live_filled_rows": 20},
        "continuation": {"median_arr_pct": 100.0, "p05_arr_pct": 60.0, "historical_arr_pct": 90.0},
    }
    raw_but_thin = {
        "candidate_family": "global_profile",
        "profile": {"name": "raw_thin", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49},
        "historical": {"replay_live_filled_rows": 6},
        "continuation": {"median_arr_pct": 190.0, "p05_arr_pct": 100.0, "historical_arr_pct": 170.0},
    }
    live_balanced = {
        "candidate_family": "regime_policy",
        "profile": {"name": "live_balanced", "max_abs_delta": 0.00012, "up_max_buy_price": 0.49, "down_max_buy_price": 0.5},
        "historical": {"replay_live_filled_rows": 18},
        "continuation": {"median_arr_pct": 170.0, "p05_arr_pct": 96.0, "historical_arr_pct": 150.0},
    }
    drag_context = {
        "total_rows": 40,
        "skip_price_count": 15,
        "order_failed_count": 12,
        "cancelled_unfilled_count": 4,
        "skip_rate": 0.375,
        "order_failure_rate": 0.3,
        "cancelled_unfilled_rate": 0.1,
        "direction_stats": {},
    }
    best_live, best_raw, ranked, drag = _rank_candidate_packages(
        active_candidate=active,
        candidates=[
            ("active_profile", active),
            ("global_best_candidate", raw_but_thin),
            ("regime_best_candidate", live_balanced),
        ],
        drag_context=drag_context,
        min_fill_retention_ratio=0.85,
    )
    assert best_raw["runtime_package"]["profile"]["name"] == "raw_thin"
    assert best_live["runtime_package"]["profile"]["name"] == "live_balanced"
    assert drag["winner_changed_due_to_execution_drag"] is True
    assert len(ranked) == 3


def test_rank_candidate_packages_prefers_validated_regime_baseline_over_weak_probe_only_package() -> None:
    active = {
        "candidate_family": "global_profile",
        "profile": {"name": "active", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "historical": {"replay_live_filled_rows": 20},
        "continuation": {"median_arr_pct": 100.0, "p05_arr_pct": 60.0, "historical_arr_pct": 90.0},
        "scoring": {"generalization_ratio": 0.92, "evidence_band": "validated", "candidate_class": "hold_current"},
    }
    validated_regime = {
        "candidate_family": "regime_policy",
        "profile": {"name": "regime_validated", "max_abs_delta": 0.00012, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "base_profile": {"name": "active", "max_abs_delta": 0.00015, "up_max_buy_price": 0.49, "down_max_buy_price": 0.51},
        "session_overrides": [{"session_name": "open_et", "et_hours": [9, 10, 11], "profile": {"name": "tight_down", "max_abs_delta": 0.0001, "up_max_buy_price": 0.48, "down_max_buy_price": 0.49}}],
        "historical": {"replay_live_filled_rows": 18},
        "continuation": {"median_arr_pct": 132.0, "p05_arr_pct": 78.0, "historical_arr_pct": 121.0},
        "scoring": {"generalization_ratio": 0.88, "evidence_band": "validated", "candidate_class": "hold_current"},
        "candidate_class": "hold_current",
        "execution_realism_score": 0.91,
        "evidence_band": "validated",
    }
    weak_probe = {
        "candidate_family": "hypothesis",
        "profile": {"name": "probe_spike", "max_abs_delta": 0.00005, "up_max_buy_price": 0.47, "down_max_buy_price": 0.48},
        "historical": {"replay_live_filled_rows": 4},
        "continuation": {"median_arr_pct": 185.0, "p05_arr_pct": 105.0, "historical_arr_pct": 170.0},
        "scoring": {"generalization_ratio": 0.42, "evidence_band": "exploratory", "candidate_class": "probe_only"},
        "candidate_class": "probe_only",
        "execution_realism_score": 0.44,
        "evidence_band": "exploratory",
    }
    drag_context = {
        "total_rows": 40,
        "skip_price_count": 12,
        "order_failed_count": 8,
        "cancelled_unfilled_count": 3,
        "skip_rate": 0.3,
        "order_failure_rate": 0.2,
        "cancelled_unfilled_rate": 0.075,
        "direction_stats": {},
    }

    best_live, best_raw, ranked, _ = _rank_candidate_packages(
        active_candidate=active,
        candidates=[
            ("active_profile", active),
            ("regime_best_candidate", validated_regime),
            ("hypothesis_best_candidate", weak_probe),
        ],
        drag_context=drag_context,
        min_fill_retention_ratio=0.85,
    )

    assert best_raw["runtime_package"]["profile"]["name"] == "probe_spike"
    assert best_live["runtime_package"]["profile"]["name"] == "regime_validated"
    assert best_live["candidate_class"] == "hold_current"
    assert best_live["execution_realism_score"] > weak_probe["execution_realism_score"]
    assert ranked[0]["runtime_package"]["profile"]["name"] == "probe_spike"


def test_one_sided_bias_recommendation_flags_down_strength_and_up_suppression() -> None:
    rows = [
        {"order_status": "live_filled", "direction": "DOWN", "pnl_usd": 3.0},
        {"order_status": "live_filled", "direction": "DOWN", "pnl_usd": 2.0},
        {"order_status": "live_filled", "direction": "UP", "pnl_usd": -1.0},
        {"order_status": "skip_price_outside_guardrails", "direction": "UP"},
        {"order_status": "skip_price_outside_guardrails", "direction": "UP"},
    ]
    recommendation = _one_sided_bias_recommendation(rows)
    assert recommendation["recommendation"] in {"tighten_down_and_suppress_up", "suppress_up"}
    assert recommendation["down_filled_pnl_usd"] > recommendation["up_filled_pnl_usd"]


def test_build_hypothesis_candidate_uses_summary_contract() -> None:
    payload = {
        "best_candidate": {
            "name": "hyp_down_early",
            "max_abs_delta": 0.0001,
            "up_max_buy_price": 0.48,
            "down_max_buy_price": 0.49,
            "session_name": "open_et",
            "et_hours": [9, 10],
            "validation_live_filled_rows": 11,
            "validation_median_arr_pct": 250.0,
            "validation_p05_arr_pct": 120.0,
            "validation_replay_pnl_usd": 16.4,
            "validation_profit_probability": 0.7,
            "validation_p95_drawdown_usd": 1.9,
            "generalization_ratio": 0.88,
        },
        "best_hypothesis": {
            "summary": {
                "validation_replay_pnl_usd": 14.2,
                "validation_profit_probability": 0.62,
                "validation_p95_drawdown_usd": 2.5,
            }
        },
    }
    candidate = _build_hypothesis_candidate(payload)
    assert candidate is not None
    assert candidate["candidate_family"] == "hypothesis"
    assert candidate["historical"]["replay_live_filled_rows"] == 11
    assert candidate["historical"]["replay_live_filled_pnl_usd"] == 16.4
    assert candidate["monte_carlo"]["profit_probability"] == 0.7
    assert candidate["monte_carlo"]["p95_max_drawdown_usd"] == 1.9
    assert candidate["continuation"]["median_arr_pct"] == 250.0
