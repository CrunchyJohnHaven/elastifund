from __future__ import annotations

from pathlib import Path

from scripts.run_btc5_autoresearch_cycle import (
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


def test_write_reports_keeps_artifacts_in_both_json_outputs(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-03-09T18:30:00Z",
        "decision": {"action": "hold", "reason": "current_profile_is_best", "median_arr_delta_pct": 0.0, "historical_arr_delta_pct": 0.0, "p05_arr_delta_pct": 0.0},
        "active_profile": {"name": "current_live_profile"},
        "best_candidate": {"profile": {"name": "current_live_profile"}},
        "simulation_summary": {"input": {"observed_window_rows": 75, "live_filled_rows": 45}},
    }
    artifacts = _write_reports(tmp_path, payload)
    cycle_text = Path(artifacts["cycle_json"]).read_text()
    latest_text = Path(artifacts["latest_json"]).read_text()
    assert '"artifacts"' in cycle_text
    assert '"artifacts"' in latest_text


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
