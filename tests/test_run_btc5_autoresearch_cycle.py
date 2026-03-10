from __future__ import annotations

from pathlib import Path

from scripts.run_btc5_autoresearch_cycle import (
    _build_hypothesis_candidate,
    _capital_scale_recommendation,
    _deploy_recommendation,
    _execution_drag_context,
    _fund_reconciliation_blocked,
    _live_fill_windows,
    _one_sided_bias_recommendation,
    _rank_candidate_packages,
    _select_public_forecast,
    _runtime_session_policy_from_overrides,
    _load_env_file,
    _merged_strategy_env,
    _profile_from_env,
    _promotion_decision,
    _write_reports,
    render_strategy_env,
)


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
    assert decision["median_arr_delta_pct"] > 0.0


def test_promotion_decision_holds_when_arr_does_not_improve() -> None:
    best = {
        "profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "base_profile": {"name": "grid", "max_abs_delta": 0.0001, "up_max_buy_price": 0.49, "down_max_buy_price": 0.50},
        "session_overrides": [],
        "historical": {"replay_live_filled_pnl_usd": 44.0, "replay_live_filled_rows": 24},
        "monte_carlo": {"median_total_pnl_usd": 52.0, "profit_probability": 0.965, "p95_max_drawdown_usd": 22.0, "loss_limit_hit_probability": 0.11},
        "continuation": {"historical_arr_pct": 1300.0, "median_arr_pct": 1390.0, "p05_arr_pct": 380.0},
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
        min_median_arr_improvement_pct=5.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
    )
    assert decision["action"] == "hold"
    assert "median_arr_delta_below_threshold" in decision["reason"]


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


def test_write_reports_keeps_artifacts_in_both_json_outputs(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-03-09T18:30:00Z",
        "decision": {"action": "hold", "reason": "current_profile_is_best", "median_arr_delta_pct": 0.0, "historical_arr_delta_pct": 0.0, "p05_arr_delta_pct": 0.0},
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
        "simulation_summary": {"input": {"observed_window_rows": 75, "live_filled_rows": 45}},
    }
    artifacts = _write_reports(tmp_path, payload)
    cycle_text = Path(artifacts["cycle_json"]).read_text()
    latest_text = Path(artifacts["latest_json"]).read_text()
    latest_md = Path(artifacts["latest_md"]).read_text()
    assert '"artifacts"' in cycle_text
    assert '"artifacts"' in latest_text
    assert '"runtime_load_status"' in latest_text
    assert "Runtime Load Status" in latest_md
    assert "Override env written" in latest_md


def test_deploy_recommendation_promote_shadow_hold() -> None:
    decision = {
        "median_arr_delta_pct": 0.2,
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
            decision={"median_arr_delta_pct": 0.0, "profit_probability_delta": 0.0, "p95_drawdown_delta_usd": 1.0},
            validation_live_filled_rows=10,
            generalization_ratio=0.9,
        )
        == "hold"
    )


def test_select_public_forecast_prefers_confidence_then_deploy_then_recency() -> None:
    standard = {
        "generated_at": "2026-03-09T18:00:00+00:00",
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
    }
    probe = {
        "generated_at": "2026-03-09T18:30:00+00:00",
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
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=True,
        fund_reconciliation_blocked=False,
        fund_block_reasons=[],
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
        package_confidence_label="high",
        trailing=trailing,
        promoted_package_selected=True,
        fund_reconciliation_blocked=True,
        fund_block_reasons=["accounting_reconciliation_drift"],
    )
    assert recommendation["status"] == "test_add"
    assert recommendation["recommended_tranche_usd"] == 100


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
    assert candidate["continuation"]["median_arr_pct"] == 250.0
