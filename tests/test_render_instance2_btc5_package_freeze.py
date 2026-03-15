from __future__ import annotations

from scripts.render_instance2_btc5_package_freeze import build_contract, render_markdown


def test_build_contract_freezes_btc5_recovery_package_and_shadow_sequence() -> None:
    contract = build_contract(
        runtime_truth={
            "agent_run_mode": "shadow",
            "allow_order_submission": False,
            "block_reasons": ["service_not_running", "remote_runtime_storage_blocked"],
            "btc5_selected_package": {
                "runtime_package_loaded": False,
                "selected_best_profile_name": "policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51",
                "selected_package_confidence_label": "medium",
            },
            "btc5_stage_readiness": {"allowed_stage": 0, "can_trade_now": False},
        },
        state_improvement={
            "metrics": {"candidate_to_trade_conversion": 0.0},
            "per_venue_candidate_counts": {"polymarket": 2, "kalshi": 0},
            "per_venue_executed_notional_usd": {"combined_hourly": 0.0},
            "improvement_velocity": {"deltas": {"candidate_to_trade_conversion_delta": 0.0}},
            "strategy_recommendations": {
                "btc5_candidate_recovery": {
                    "champion_lane": {"top_candidate_id": "btc5:grid_d0.00005_up0.48_down0.51"},
                    "comparison_only_lanes": ["btc_15m", "eth_intraday", "btc_4h"],
                },
                "champion_lane_contract": {
                    "required_outputs": {"arr_confidence_score": 0.49},
                    "blocker_classes": {
                        "candidate": {"checks": ["runtime_package_load_pending"]},
                        "confirmation": {"checks": ["confirmation_coverage_insufficient"]},
                    },
                },
                "control_plane_consistency": {
                    "capital_consistency": {
                        "artifacts": {
                            "strategy_scale_comparison": {
                                "stage_readiness": {
                                    "order_failed_rate_recent_40": 0.025,
                                    "trailing_12_live_filled_pnl_usd": -8.5465,
                                    "trailing_40_live_filled_pnl_usd": -24.0875,
                                }
                            }
                        }
                    }
                },
            },
        },
        public_runtime_snapshot={
            "launch": {"posture": "blocked"},
            "service": {"status": "stopped"},
            "btc_5min_maker": {
                "live_filled_rows": 138,
                "live_filled_pnl_usd": 85.3018,
                "intraday_live_summary": {
                    "filled_pnl_usd_today": -25.8918,
                    "recent_20_pnl_usd": -28.1442,
                },
            },
        },
        improvement_velocity={},
        finance_latest={"finance_gate_pass": True, "finance_gate": {"pass": True}},
        finance_action_queue={
            "actions": [
                {
                    "action_key": "allocate::fund_trading",
                    "amount_usd": 250.0,
                    "executed_at": "2026-03-10T21:15:01+00:00",
                }
            ]
        },
        selected_package={"arr_tracking": {"median_arr_delta_pct": 2482624.0209}},
        current_probe={},
        strategy_scale_comparison={},
        signal_source_audit={},
    )

    assert contract["package_freeze"]["post_upgrade_shadow_package"]["package_id"] == "btc5:grid_d0.00005_up0.48_down0.51"
    assert contract["package_freeze"]["comparison_only_package"]["package_id"] == (
        "policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51"
    )
    assert [step["name"] for step in contract["post_upgrade_shadow_sequence"]] == [
        "package_load",
        "candidate_scan",
        "order_failure_check",
        "executed_notional_check",
    ]
    assert contract["post_upgrade_shadow_sequence"][2]["current_observation"]["order_failed_rate_recent_40"] == 0.025
    assert contract["required_outputs"]["candidate_delta_arr_bps"] == 248262402
    assert contract["required_outputs"]["arr_confidence_score"] == 0.49
    assert contract["required_outputs"]["finance_gate_pass"] is True


def test_render_markdown_mentions_shadow_sequence_and_capital_hold() -> None:
    contract = {
        "status": "upgrade_blocked",
        "truth_snapshot": {
            "runtime_package_loaded": False,
            "polymarket_candidates_total": 2,
            "order_failed_rate_recent_40": 0.025,
            "executed_notional_usd_last_hour": 0.0,
            "candidate_to_trade_conversion_last_hour": 0.0,
            "btc5_recent_12_live_filled_pnl_usd": -8.5465,
            "btc5_recent_20_live_filled_pnl_usd": -28.1442,
        },
        "package_freeze": {
            "champion_lane": "btc_5m",
            "post_upgrade_shadow_package": {"package_id": "btc5:grid_d0.00005_up0.48_down0.51"},
            "comparison_only_package": {
                "package_id": "policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51"
            },
            "comparison_only_lanes": ["btc_15m", "eth_intraday", "btc_4h"],
        },
        "post_upgrade_shadow_sequence": [
            {"step": 1, "name": "package_load"},
            {"step": 2, "name": "candidate_scan"},
            {"step": 3, "name": "order_failure_check"},
            {"step": 4, "name": "executed_notional_check"},
        ],
        "required_outputs": {
            "candidate_delta_arr_bps": 248262402,
            "expected_improvement_velocity_delta": 0.0,
            "arr_confidence_score": 0.49,
            "finance_gate_pass": True,
            "one_next_cycle_action": "Load the package in shadow and hold scale.",
        },
    }

    markdown = render_markdown(contract)

    assert "Post-Upgrade Shadow Sequence" in markdown
    assert "`package_load`" in markdown
    assert "`order_failure_check`" in markdown
    assert "The incoming `2000 USD` stays in reserve." in markdown
