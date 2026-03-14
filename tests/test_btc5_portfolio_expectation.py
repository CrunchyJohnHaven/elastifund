from __future__ import annotations

from scripts.btc5_portfolio_expectation import build_expectation_summary, render_markdown


def test_build_expectation_summary_scales_candidates_to_wallet() -> None:
    current_probe = {
        "deploy_recommendation": "shadow_only",
        "decision": {
            "reason": "probe_feedback_blocks_promotion",
            "probe_gate_reason_tags": ["trailing_12_live_filled_non_positive"],
        },
        "capital_stage_recommendation": {"stage_reason": "hold_stage1_trailing12_not_positive"},
        "capital_scale_recommendation": {"status": "hold"},
        "execution_drag_summary": {"order_failure_rate": 0.1},
        "current_candidate": {
            "profile": {"name": "current_live_profile"},
            "historical": {
                "replay_live_filled_rows": 20,
                "replay_attempt_rows": 25,
                "trade_notional_usd": 200.0,
                "replay_live_filled_pnl_usd": 10.0,
            },
            "continuation": {"avg_trade_size_usd": 10.0},
            "monte_carlo": {
                "avg_active_trades": 18.0,
                "median_total_pnl_usd": -4.0,
                "mean_total_pnl_usd": -2.0,
                "p05_total_pnl_usd": -20.0,
                "p95_total_pnl_usd": 12.0,
                "profit_probability": 0.3,
                "p95_max_drawdown_usd": 50.0,
                "loss_limit_hit_probability": 0.6,
            },
        },
        "best_candidate": {
            "profile": {"name": "policy_current_live_profile__open_et__grid"},
            "candidate_class": "promote",
            "generalization_ratio": 1.02,
            "recommended_session_policy": [{"name": "open_et", "et_hours": [9, 10, 11]}],
            "historical": {
                "replay_live_filled_rows": 22,
                "replay_attempt_rows": 26,
                "trade_notional_usd": 220.0,
                "replay_live_filled_pnl_usd": 14.0,
            },
            "continuation": {"avg_trade_size_usd": 10.0},
            "monte_carlo": {
                "avg_active_trades": 20.0,
                "median_total_pnl_usd": 6.0,
                "mean_total_pnl_usd": 8.0,
                "p05_total_pnl_usd": -10.0,
                "p95_total_pnl_usd": 20.0,
                "profit_probability": 0.62,
                "p95_max_drawdown_usd": 30.0,
                "loss_limit_hit_probability": 0.4,
            },
        },
    }
    runtime_truth = {
        "accounting_reconciliation": {
            "remote_wallet_counts": {
                "total_wallet_value_usd": 500.0,
                "free_collateral_usd": 400.0,
            }
        }
    }
    baseline = {
        "deduped_rows": 100,
        "deduped_live_filled_rows": 40,
        "rows_by_source": {"remote_probe:cache": 100},
        "first_window_start_ts": 1000,
        "last_window_start_ts": 36700,
    }
    regime_summary = {
        "high_conviction_followups": [
            {
                "name": "policy_current_live_profile__hour_et_11__grid",
                "validation_live_filled_rows": 50,
                "validation_profit_probability": 0.7,
                "validation_p05_arr_pct": 1000.0,
                "frontier_focus_tags": ["session_conditioned"],
            }
        ],
        "loss_cluster_filters": [
            {
                "filter_name": "down_open_et_0.49_to_0.51_le_0.00005",
                "session_name": "open_et",
                "direction": "DOWN",
                "price_bucket": "0.49_to_0.51",
                "delta_bucket": "le_0.00005",
                "total_loss_usd": -25.0,
            }
        ],
        "size_ready_followups": [
            {
                "name": "policy_current_live_profile__hour_et_11__grid",
                "size_readiness_status": "needs_more_size_evidence",
                "validation_live_filled_rows": 50,
                "shadow_trade_sizes_usd": [],
            }
        ],
    }
    hypothesis_summary = {}

    summary = build_expectation_summary(
        current_probe=current_probe,
        runtime_truth=runtime_truth,
        baseline=baseline,
        regime_summary=regime_summary,
        hypothesis_summary=hypothesis_summary,
    )

    assert summary["observed_window"]["sample_span_hours"] == 10.0
    assert summary["current_live"]["expected_pnl_30d_usd"] == -288.0
    assert summary["current_live"]["expected_pnl_annualized_usd"] == -3504.0
    assert summary["best_validated_variant"]["expected_pnl_30d_usd"] == 432.0
    assert summary["best_validated_variant"]["expected_pnl_annualized_usd"] == 5256.0
    assert summary["best_validated_variant"]["edge_status"]["status"] == "positive_but_tail_risky"
    assert summary["delta_vs_current"]["expected_pnl_30d_usd"] == 720.0
    assert [item["category"] for item in summary["next_simulations"]] == [
        "regime_policy_followup",
        "loss_cluster_revalidation",
        "capacity_revalidation",
    ]


def test_render_markdown_surfaces_wallet_scaled_numbers() -> None:
    summary = {
        "generated_at": "2026-03-11T18:00:00+00:00",
        "portfolio": {"wallet_value_usd": 500.0, "free_collateral_usd": 400.0},
        "observed_window": {"sample_span_hours": 10.0, "decision_rows": 100, "live_filled_rows": 40},
        "current_live": {
            "expected_pnl_30d_usd": -288.0,
            "expected_pnl_annualized_usd": -3504.0,
            "expected_fills_per_day": 43.2,
            "profit_probability": 0.3,
            "p95_drawdown_usd": 50.0,
            "p95_drawdown_pct_of_wallet": 10.0,
            "edge_status": {
                "status": "historical_positive_but_mc_negative",
                "reason": "historical_replay_positive_but_bootstrap_paths_fail",
            },
        },
        "best_validated_variant": {
            "profile_name": "policy_current_live_profile__open_et__grid",
            "expected_pnl_30d_usd": 432.0,
            "expected_pnl_annualized_usd": 5256.0,
            "expected_fills_per_day": 48.0,
            "profit_probability": 0.62,
            "p95_drawdown_usd": 30.0,
            "p95_drawdown_pct_of_wallet": 6.0,
            "edge_status": {
                "status": "positive_but_tail_risky",
                "reason": "median_positive_but_tail_still_negative",
            },
        },
        "validation_state": {
            "deploy_recommendation": "shadow_only",
            "decision": {
                "reason": "probe_feedback_blocks_promotion",
                "probe_gate_reason_tags": ["trailing_12_live_filled_non_positive"],
            },
            "capital_stage_recommendation": {"stage_reason": "hold_stage1_trailing12_not_positive"},
        },
        "next_simulations": [
            {
                "title": "policy_current_live_profile__hour_et_11__grid",
                "category": "regime_policy_followup",
                "why": "Highest-conviction validated session-conditioned upgrade in the regime lab.",
            }
        ],
    }

    markdown = render_markdown(summary)

    assert "Expected PnL over next 30d at current cadence: `$-288.00`" in markdown
    assert "Expected annualized PnL on current wallet: `$5256.00`" in markdown
    assert "`policy_current_live_profile__hour_et_11__grid` [regime_policy_followup]" in markdown
