from __future__ import annotations

from datetime import datetime, timezone

from scripts.render_instance2_bounded_envelope import build_bounded_envelope


UTC = timezone.utc


def test_build_bounded_envelope_locks_canonical_live_and_frontier_shadow() -> None:
    rows = [
        {
            "window_start_ts": 1,
            "updated_at": "2026-03-12T22:00:00+00:00",
            "order_status": "live_filled",
            "direction": "UP",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "gt_0.00010",
            "session_name": "open_et",
            "et_hour": 10,
            "realized_pnl_usd": -12.1,
            "won": False,
        },
        {
            "window_start_ts": 2,
            "updated_at": "2026-03-12T22:05:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "lt_0.49",
            "delta_bucket": "le_0.00005",
            "session_name": "open_et",
            "et_hour": 10,
            "realized_pnl_usd": -11.9,
            "won": False,
        },
        {
            "window_start_ts": 3,
            "updated_at": "2026-03-12T22:10:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "lt_0.49",
            "delta_bucket": "le_0.00005",
            "session_name": "hour_et_19",
            "et_hour": 19,
            "realized_pnl_usd": 13.4,
            "won": True,
        },
        {
            "window_start_ts": 4,
            "updated_at": "2026-03-12T22:15:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "le_0.00005",
            "session_name": "hour_et_19",
            "et_hour": 19,
            "realized_pnl_usd": 12.8,
            "won": True,
        },
        {
            "window_start_ts": 5,
            "updated_at": "2026-03-12T22:20:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "0.00005_to_0.00010",
            "session_name": "open_et",
            "et_hour": 11,
            "realized_pnl_usd": -9.5,
            "won": False,
        },
    ]
    regime_summary = {
        "candidates": [
            {
                "candidate_class": "promote",
                "candidate_class_reason_tags": ["validated_clear_upgrade"],
                "follow_up_families": ["down_only", "tight_delta_down_bias"],
                "historical": {
                    "replay_live_filled_rows": 110,
                    "replay_live_filled_pnl_usd": 115.2268,
                    "trade_notional_usd": 550.0,
                },
                "continuation": {"p05_arr_pct": 658198.116},
                "monte_carlo": {"profit_probability": 0.985, "p95_max_drawdown_usd": 63.1342},
                "scoring": {"live_policy_score": 5045018.8923},
                "policy": {
                    "name": "policy_current_live_profile__hour_et_19__grid_d0.00005_up0.00_down0.49",
                    "default_profile": {
                        "name": "current_live_profile",
                        "max_abs_delta": 0.00075,
                        "up_max_buy_price": 0.49,
                        "down_max_buy_price": 0.51,
                    },
                    "overrides": [
                        {
                            "session_name": "hour_et_19",
                            "et_hours": [19],
                            "profile": {
                                "name": "grid_d0.00005_up0.00_down0.49",
                                "max_abs_delta": 0.00005,
                                "up_max_buy_price": 0.0,
                                "down_max_buy_price": 0.49,
                            },
                        }
                    ],
                },
            }
        ],
        "best_probe_only_candidate": {
            "name": "policy_current_live_profile__open_et__grid_d0.00005_up0.48_down0.48",
            "candidate_class": "probe_only",
            "candidate_class_reason_tags": ["requires_revalidation_or_fill_retention_recovery"],
            "follow_up_families": ["probe_only_exploratory"],
            "default_profile": {
                "name": "current_live_profile",
                "max_abs_delta": 0.00075,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            },
            "session_policy": [
                {
                    "name": "open_et",
                    "et_hours": [9, 10, 11],
                    "max_abs_delta": 0.00005,
                    "up_max_buy_price": 0.48,
                    "down_max_buy_price": 0.48,
                }
            ],
            "validation_live_filled_rows": 100,
            "validation_replay_pnl_usd": 91.7708,
            "validation_profit_probability": 0.95,
            "validation_p95_drawdown_usd": 67.0518,
            "validation_p05_arr_pct": 38735.9429,
            "generalization_ratio": 0.8333,
            "ranking_score": 1976496.9356,
        },
    }
    current_probe = {
        "live_fill_freshness_hours": 8.0,
        "trailing_12_live_filled_pnl_usd": -33.5,
        "trailing_40_live_filled_pnl_usd": -7.3,
        "trailing_120_live_filled_pnl_usd": -7.3,
        "validation_live_filled_rows": 226,
        "stage_not_ready_reason_tags": [
            "trailing_12_live_filled_non_positive",
            "recent_loss_cluster_flags_present",
            "live_fills_stale_gt_6h",
        ],
        "current_candidate": {
            "historical": {
                "replay_live_filled_pnl_usd": 95.0,
                "trade_notional_usd": 550.0,
            }
        },
        "best_candidate": {
            "policy": {
                "name": "policy_current_live_profile__hour_et_11__grid_d0.00015_up0.51_down0.51",
                "overrides": [
                    {
                        "session_name": "hour_et_11",
                        "et_hours": [11],
                        "profile": {
                            "name": "grid_d0.00015_up0.51_down0.51",
                            "max_abs_delta": 0.00015,
                            "up_max_buy_price": 0.51,
                            "down_max_buy_price": 0.51,
                        },
                    }
                ],
            }
        },
    }
    policy_latest = {
        "selected_policy_id": "active_profile_probe_d0_00075",
        "selected_best_runtime_package": {
            "profile": {
                "name": "active_profile_probe_d0_00075",
                "max_abs_delta": 0.00075,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            },
            "session_policy": [],
        },
        "frontier_best_candidate": {
            "policy_id": "active_profile",
            "loss_improvement_vs_incumbent": 709.9664,
            "runtime_package": {
                "profile": {
                    "name": "active_profile",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
        },
    }
    runtime_truth = {
        "allow_order_submission": True,
        "btc5_baseline_live_allowed": True,
        "btc5_stage_upgrade_can_trade_now": False,
        "btc5_selected_package": {
            "selected_policy_id": "active_profile_probe_d0_00075",
            "selected_best_profile_name": "active_profile_probe_d0_00075",
        },
        "btc5_stage_readiness": {
            "stage_upgrade_trade_now_blocking_checks": [
                "wallet_export_stale",
                "confirmation_coverage_insufficient",
            ]
        },
    }
    finance_latest = {
        "finance_gate_pass": True,
        "treasury_gate_pass": False,
        "capital_expansion_only_hold": True,
    }

    payload = build_bounded_envelope(
        runtime_truth=runtime_truth,
        finance_latest=finance_latest,
        current_probe=current_probe,
        policy_latest=policy_latest,
        regime_summary=regime_summary,
        rows=rows,
        generated_at=datetime(2026, 3, 12, 23, 1, tzinfo=UTC),
    )

    assert payload["snapshot"]["current_et_hour"] == 19
    assert payload["live_profile_recommendation"]["candidate_name"] == "active_profile_probe_d0_00075"
    assert payload["live_profile_recommendation"]["selection_reasons"] == ["canonical_live_baseline_locked"]
    assert payload["live_profile_recommendation"]["runtime_package"]["effective_profile_for_current_hour"]["up_max_buy_price"] == 0.49
    assert payload["shadow_profile_recommendation"]["candidate_name"] == "active_profile"
    assert payload["loss_surface"]["recent_12_live_filled"]["by_fill_outcome"] == (
        payload["loss_surface"]["recent_12_live_filled"]["by_holding_outcome"]
    )
    assert payload["probe_loss_cluster_snapshot"]["source_artifact"] == "reports/btc5_autoresearch_current_probe/latest.json"
    assert payload["suppression_contract"]["positive_cycle_clearance_required"] == 2
    assert payload["five_filter_shadow_overlay"]["decision"] == "reject_immediately"
    assert payload["five_filter_shadow_overlay"]["candidate_density"]["avg_candidate_windows_per_day"] == 1.0
    assert payload["five_filter_shadow_overlay"]["matched_window_comparison"]["matched_window_expectancy_lift_usd"] == 0.0
    assert payload["required_outputs"]["candidate_delta_arr_bps"] == 40
    assert payload["required_outputs"]["expected_improvement_velocity_delta"] == 0.03
    assert payload["required_outputs"]["finance_gate_pass"] is True
    assert any("Hold the UP side" in reason for reason in payload["required_outputs"]["block_reasons"])
    assert any("`active_profile` shadow-only" in reason for reason in payload["required_outputs"]["block_reasons"])
    assert any("hour_et_11" in reason for reason in payload["required_outputs"]["block_reasons"])
    assert any("Reject the five-filter shadow overlay" in reason for reason in payload["required_outputs"]["block_reasons"])
    assert "Keep `active_profile_probe_d0_00075` live" in payload["required_outputs"]["one_next_cycle_action"]
    assert "`active_profile` as the only same-stream shadow comparator" in payload["required_outputs"]["one_next_cycle_action"]


def test_build_bounded_envelope_holds_when_no_current_hour_candidate_exists() -> None:
    payload = build_bounded_envelope(
        runtime_truth={"allow_order_submission": True, "btc5_baseline_live_allowed": True},
        finance_latest={"finance_gate_pass": True, "treasury_gate_pass": False, "capital_expansion_only_hold": True},
        current_probe={"live_fill_freshness_hours": 9.0, "stage_not_ready_reason_tags": []},
        regime_summary={"candidates": []},
        rows=[],
        generated_at=datetime(2026, 3, 12, 23, 1, tzinfo=UTC),
    )

    assert payload["live_profile_recommendation"]["status"] == "hold_live_changes"
    assert payload["required_outputs"]["candidate_delta_arr_bps"] == 0
    assert payload["required_outputs"]["expected_improvement_velocity_delta"] == -0.05


def test_build_bounded_envelope_keeps_canonical_live_when_current_hour_candidate_is_looser() -> None:
    rows = [
        {
            "window_start_ts": 1,
            "updated_at": "2026-03-12T23:05:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "le_0.00005",
            "session_name": "hour_et_19",
            "et_hour": 19,
            "realized_pnl_usd": 5.2,
            "won": True,
        },
        {
            "window_start_ts": 2,
            "updated_at": "2026-03-12T23:10:00+00:00",
            "order_status": "live_filled",
            "direction": "DOWN",
            "price_bucket": "0.49_to_0.51",
            "delta_bucket": "le_0.00005",
            "session_name": "hour_et_19",
            "et_hour": 19,
            "realized_pnl_usd": 4.8,
            "won": True,
        },
    ]
    regime_summary = {
        "hold_current_candidate": {
            "name": "policy_current_live_profile",
            "candidate_class": "hold_current",
            "candidate_class_reason_tags": ["active_profile_baseline"],
            "default_profile": {
                "name": "current_live_profile",
                "max_abs_delta": 0.00005,
                "up_max_buy_price": 0.0,
                "down_max_buy_price": 0.49,
            },
            "session_policy": [],
            "validation_live_filled_rows": 120,
            "validation_replay_pnl_usd": 95.2208,
            "validation_profit_probability": 0.93,
            "validation_p95_drawdown_usd": 73.0,
            "validation_p05_arr_pct": 11_000.0,
            "generalization_ratio": 1.0,
            "ranking_score": 1_483_259.4484,
        },
        "candidates": [
            {
                "candidate_class": "promote",
                "candidate_class_reason_tags": ["validated_clear_upgrade"],
                "follow_up_families": ["current_hour_looser_probe"],
                "historical": {
                    "replay_live_filled_rows": 140,
                    "replay_live_filled_pnl_usd": 140.0,
                    "trade_notional_usd": 550.0,
                },
                "continuation": {"p05_arr_pct": 700_000.0},
                "monte_carlo": {"profit_probability": 0.98, "p95_max_drawdown_usd": 60.0},
                "scoring": {"live_policy_score": 6_500_000.0},
                "policy": {
                    "name": "policy_hour_et_19_looser_probe",
                    "default_profile": {
                        "name": "current_live_profile",
                        "max_abs_delta": 0.00005,
                        "up_max_buy_price": 0.0,
                        "down_max_buy_price": 0.49,
                    },
                    "overrides": [
                        {
                            "session_name": "hour_et_19",
                            "et_hours": [19],
                            "profile": {
                                "name": "grid_d0.00010_up0.49_down0.49",
                                "max_abs_delta": 0.00010,
                                "up_max_buy_price": 0.49,
                                "down_max_buy_price": 0.49,
                            },
                        }
                    ],
                },
            }
        ],
    }
    current_probe = {
        "live_fill_freshness_hours": 2.0,
        "validation_live_filled_rows": 120,
        "stage_not_ready_reason_tags": [],
        "current_candidate": {
            "historical": {
                "replay_live_filled_pnl_usd": 95.2208,
                "trade_notional_usd": 550.0,
            }
        },
    }
    policy_latest = {
        "selected_policy_id": "active_profile_probe_d0_00075",
        "selected_best_runtime_package": {
            "profile": {
                "name": "active_profile_probe_d0_00075",
                "max_abs_delta": 0.00075,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            },
            "session_policy": [],
        },
        "frontier_best_candidate": {
            "policy_id": "active_profile",
            "loss_improvement_vs_incumbent": 709.9664,
            "runtime_package": {
                "profile": {
                    "name": "active_profile",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
        },
    }
    runtime_truth = {
        "allow_order_submission": True,
        "btc5_baseline_live_allowed": True,
        "btc5_stage_upgrade_can_trade_now": False,
        "btc5_selected_package": {
            "selected_policy_id": "active_profile_probe_d0_00075",
            "selected_best_profile_name": "active_profile_probe_d0_00075",
        },
        "btc5_stage_readiness": {"stage_upgrade_trade_now_blocking_checks": []},
    }
    finance_latest = {
        "finance_gate_pass": True,
        "treasury_gate_pass": False,
        "capital_expansion_only_hold": True,
    }

    payload = build_bounded_envelope(
        runtime_truth=runtime_truth,
        finance_latest=finance_latest,
        current_probe=current_probe,
        policy_latest=policy_latest,
        regime_summary=regime_summary,
        rows=rows,
        generated_at=datetime(2026, 3, 12, 23, 20, tzinfo=UTC),
    )

    assert payload["live_profile_recommendation"]["candidate_name"] == "active_profile_probe_d0_00075"
    assert payload["live_profile_recommendation"]["selection_reasons"] == ["canonical_live_baseline_locked"]
    assert payload["shadow_profile_recommendation"]["candidate_name"] == "active_profile"
    assert payload["required_outputs"]["candidate_delta_arr_bps"] == 40
    assert payload["required_outputs"]["expected_improvement_velocity_delta"] == 0.03
    assert "Keep `active_profile_probe_d0_00075` live at flat stage-1 size" in payload["required_outputs"]["one_next_cycle_action"]
