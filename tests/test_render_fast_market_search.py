from __future__ import annotations

import json
from pathlib import Path

from scripts.render_fast_market_search import (
    _find_latest_report,
    build_fast_market_search_report,
    write_report_artifacts,
)


def _base_autoresearch_payload() -> dict:
    return {
        "generated_at": "2026-03-10T15:40:21.873007+00:00",
        "package_confidence_label": "high",
        "selected_package_confidence_label": "high",
        "active_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "selected_best_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "ranked_runtime_packages": [
            {
                "candidate_family": "regime_policy",
                "fill_retention_ratio": 0.91,
                "order_failure_penalty": 0.11,
                "skip_rate_penalty": 0.21,
                "p05_arr_pct": 640000.0,
                "median_arr_pct": 2200000.0,
                "p05_arr_delta_pct": 210000.0,
                "median_arr_delta_pct": 310000.0,
                "source": "regime_best_candidate",
                "validation_live_filled_rows": 23,
                "runtime_package": {
                    "profile": {"name": "current_live_profile"},
                    "session_policy": [],
                },
                "candidate": {
                    "candidate_family": "regime_policy",
                    "historical": {
                        "replay_live_filled_rows": 23,
                        "replay_attempt_rows": 30,
                        "replay_window_rows": 40,
                    },
                    "scoring": {
                        "evidence_band": "validated",
                        "validation_live_filled_rows": 23,
                    },
                },
            },
            {
                "candidate_family": "hypothesis",
                "fill_retention_ratio": 0.31,
                "order_failure_penalty": 0.49,
                "skip_rate_penalty": 0.82,
                "p05_arr_pct": 125000.0,
                "median_arr_pct": 420000.0,
                "p05_arr_delta_pct": 11000.0,
                "median_arr_delta_pct": 27000.0,
                "source": "hypothesis_best_candidate",
                "validation_live_filled_rows": 5,
                "runtime_package": {
                    "profile": {"name": "hour_11_probe"},
                    "session_policy": [],
                },
                "candidate": {
                    "candidate_family": "hypothesis",
                    "historical": {
                        "replay_live_filled_rows": 5,
                        "replay_attempt_rows": 9,
                        "replay_window_rows": 12,
                    },
                    "scoring": {
                        "evidence_band": "exploratory",
                        "validation_live_filled_rows": 5,
                    },
                },
            },
        ],
    }


def _base_runtime_truth_payload() -> dict:
    return {
        "generated_at": "2026-03-10T16:12:03.023697+00:00",
        "wallet_flow": {"status": "ready"},
        "deployment_confidence": {
            "allowed_stage": 0,
            "allowed_stage_label": "stage_0",
            "blocking_checks": [
                "stage_1_wallet_reconciliation_not_ready",
                "confirmation_coverage_insufficient",
            ],
        },
        "btc5_stage_readiness": {
            "can_trade_now": False,
            "trade_now_blocking_checks": [
                "stage_1_wallet_reconciliation_not_ready",
                "trailing_12_live_filled_not_positive",
            ],
        },
        "btc_5min_maker": {
            "guardrail_recommendation": {
                "baseline_live_filled_pnl_usd": 85.3018,
                "baseline_live_filled_rows": 138,
                "down_max_buy_price": 0.51,
                "max_abs_delta": 0.00005,
                "replay_live_filled_pnl_usd": 107.8024,
                "replay_live_filled_rows": 109,
                "up_max_buy_price": 0.48,
            },
            "fill_attribution": {
                "best_direction": {"label": "DOWN"},
                "best_price_bucket": {"label": "<0.49"},
                "recent_direction_regime": {
                    "default_quote_ticks": 1,
                    "favored_direction": "UP",
                    "fills_considered": 12,
                    "trigger_reason": "insufficient_fills",
                    "triggered": False,
                },
            },
            "latest_trade": {"order_status": "skip_price_outside_guardrails"},
        },
    }


def _base_signal_source_audit_payload() -> dict:
    return {
        "generated_at": "2026-03-10T15:44:52.872851+00:00",
        "wallet_flow_vs_llm": {"status": "insufficient_data"},
        "btc_fast_window_confirmation": {"status": "insufficient_data"},
        "capital_ranking_support": {
            "confirmation_coverage_label": "missing",
            "confirmation_strength_label": "missing",
            "confirmation_blocking_checks": [
                "wallet_flow:source_window_rows 0 < required 3",
            ],
            "confirmation_support_status": "limited",
        },
    }


def _base_current_probe_payload() -> dict:
    return {
        "generated_at": "2026-03-10T16:31:25.106768+00:00",
        "selected_package_confidence_label": "low",
        "regime_policy_summary": {
            "best_live_followups": [
                {
                    "arr_improvement_vs_active_pct": 267718.1648,
                    "candidate_class": "promote",
                    "down_max_buy_price": 0.50,
                    "evidence_band": "validated",
                    "execution_realism_label": "high",
                    "execution_realism_score": 1.0,
                    "fill_retention_vs_active": 1.0167,
                    "max_abs_delta": 0.00010,
                    "name": "policy_current_live_profile__hour_et_11__grid_d0.00010_up0.51_down0.50",
                    "promotion_gate": "clear_for_promotion",
                    "session_count": 1,
                    "session_name": "hour_et_11",
                    "session_policy": [
                        {
                            "down_max_buy_price": 0.50,
                            "et_hours": [11],
                            "max_abs_delta": 0.00010,
                            "name": "hour_et_11",
                            "up_max_buy_price": 0.51,
                        }
                    ],
                    "up_max_buy_price": 0.51,
                    "validation_live_filled_rows": 122,
                    "validation_median_arr_pct": 1854091.9064,
                    "validation_p05_arr_pct": 191634.249,
                    "validation_p95_drawdown_usd": 69.1857,
                    "validation_profit_probability": 0.97,
                    "validation_replay_pnl_usd": 104.8338,
                }
            ],
            "loss_cluster_suppression_candidates": [
                {
                    "delta_bucket": "le_0.00005",
                    "direction": "DOWN",
                    "filter_name": "down_open_et_0.49_to_0.51_le_0.00005",
                    "loss_rows": 5,
                    "price_bucket": "0.49_to_0.51",
                    "promotion_gate": "shadow_block_until_revalidated",
                    "session_name": "open_et",
                    "severity": "high",
                    "suggested_action": "suppress_cluster_until_revalidated",
                    "total_loss_usd": -25.0107,
                }
            ],
        },
    }


def _base_hypothesis_frontier_payload() -> dict:
    return {
        "frontier_median_arr_pct": 10924714.9511,
        "frontier_p05_arr_pct": 4265134.2825,
        "latest_direction": "DOWN",
        "latest_evidence_band": "exploratory",
        "latest_finished_at": "2026-03-10T12:44:55.402965+00:00",
        "latest_generalization_ratio": 42.99,
        "latest_hypothesis_name": "hyp_down_d0.00015_up0.50_down0.51_hour_et_11",
        "latest_session_name": "hour_et_11",
        "latest_validation_live_filled_rows": 5,
    }


def _base_fastlane_payload() -> dict:
    return {
        "generated_at": "2026-03-09T11:55:02.358716+00:00",
        "universe": {
            "priority_order": ["btc_15m", "btc_5m", "btc_4h", "eth_intraday"],
        },
        "candidates": [
            {
                "title": "Bitcoin Up or Down - March 9, 7:45AM-8:00AM ET",
                "priority_lane": "btc_15m",
                "expected_maker_fill_probability": 0.87,
                "route_score": 0.0,
                "visible_depth_proxy": 7513.94,
                "data_quality_flags": [],
                "toxicity_state": "toxic",
                "reject_reason": "wallet_sparsity",
            }
        ],
    }


def _base_edge_scan_payload() -> dict:
    return {
        "generated_at": "2026-03-09T00:26:31.875417+00:00",
        "candidate_markets": [
            {
                "question": "Bitcoin Up or Down - March 8, 8:20PM-8:25PM ET",
                "source": "wallet_flow",
            }
        ],
        "lane_health": {
            "lmsr": {"status": "idle"},
        },
    }


def test_build_fast_market_search_report_ranks_validated_btc5_first() -> None:
    payload = build_fast_market_search_report(
        autoresearch=_base_autoresearch_payload(),
        runtime_truth=_base_runtime_truth_payload(),
        signal_source_audit=_base_signal_source_audit_payload(),
        fastlane_payload=_base_fastlane_payload(),
        edge_scan_payload=_base_edge_scan_payload(),
        autoresearch_source_artifact="reports/btc5_autoresearch/latest.json",
        fastlane_source_artifact="reports/poly_fastlane_candidates_20260309T115502Z.json",
        edge_scan_source_artifact="reports/edge_scan_20260309T002631Z.json",
        generated_at="2026-03-10T16:30:00+00:00",
    )

    ranked = payload["ranked_candidates"]
    assert payload["schema"] == "fast_market_search.v1"
    assert ranked[0]["market_scope"] == "btc_5m"
    assert ranked[0]["deployment_class"] == "validated_btc5_blocked"
    assert ranked[0]["validation_counts"]["validation_live_filled_rows"] == 23
    assert ranked[1]["market_scope"] == "btc_5m"
    assert any(item["market_scope"] == "btc_15m" for item in ranked)
    assert payload["summary"]["best_btc5_candidate_id"] == "btc5:current_live_profile"
    assert payload["summary"]["best_adjacent_candidate_id"] == "adjacent:btc_15m"


def test_build_fast_market_search_report_tracks_adjacent_lane_placeholders() -> None:
    payload = build_fast_market_search_report(
        autoresearch=_base_autoresearch_payload(),
        runtime_truth=_base_runtime_truth_payload(),
        signal_source_audit=_base_signal_source_audit_payload(),
        fastlane_payload=_base_fastlane_payload(),
        edge_scan_payload=_base_edge_scan_payload(),
    )

    lane_map = {item["lane"]: item for item in payload["lane_map"]}
    assert lane_map["btc_15m"]["top_deployment_class"] == "adjacent_shadow_only"
    assert lane_map["eth_intraday"]["top_candidate_id"] == "adjacent:eth_intraday"
    assert "no_candidate_markets_observed" in lane_map["eth_intraday"]["blocking_checks"]


def test_build_fast_market_search_report_includes_node4_followups() -> None:
    payload = build_fast_market_search_report(
        autoresearch=_base_autoresearch_payload(),
        current_probe=_base_current_probe_payload(),
        runtime_truth=_base_runtime_truth_payload(),
        signal_source_audit=_base_signal_source_audit_payload(),
        hypothesis_frontier=_base_hypothesis_frontier_payload(),
        fastlane_payload=_base_fastlane_payload(),
        edge_scan_payload=_base_edge_scan_payload(),
        generated_at="2026-03-10T16:35:00+00:00",
    )

    ranked = {item["candidate_id"]: item for item in payload["ranked_candidates"]}
    assert "btc5:guardrail_replay_d0.00005_up0.48_down0.51" in ranked
    assert "btc5:suppress:down_open_et_0.49_to_0.51_le_0.00005" in ranked
    assert "btc5:policy_current_live_profile__hour_et_11__grid_d0.00010_up0.51_down0.50" not in ranked

    track_map = {item["track"]: item for item in payload["search_tracks"]}
    assert track_map["session_policy_followup"]["candidate_count"] == 0
    assert track_map["guardrail_parameter_sweep"]["best_candidate_id"] == "btc5:guardrail_replay_d0.00005_up0.48_down0.51"
    assert track_map["loss_cluster_suppression"]["candidate_count"] == 1
    assert payload["summary"]["best_session_followup_candidate_id"] is None
    assert payload["exploratory_hypothesis_frontier"]["candidate_name"] == "hyp_down_d0.00015_up0.50_down0.51_hour_et_11"


def test_build_fast_market_search_report_filters_packages_outside_stage0_guardrails() -> None:
    autoresearch = _base_autoresearch_payload()
    autoresearch["ranked_runtime_packages"] = [
        {
            "candidate_family": "regime_policy",
            "fill_retention_ratio": 0.98,
            "order_failure_penalty": 0.04,
            "skip_rate_penalty": 0.11,
            "p05_arr_pct": 900000.0,
            "median_arr_pct": 2800000.0,
            "p05_arr_delta_pct": 310000.0,
            "median_arr_delta_pct": 420000.0,
            "source": "regime_best_candidate",
            "validation_live_filled_rows": 23,
            "runtime_package": {
                "profile": {
                    "name": "policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [
                    {
                        "name": "open_et",
                        "et_hours": [9, 10, 11],
                        "max_abs_delta": 0.00015,
                        "up_max_buy_price": 0.51,
                        "down_max_buy_price": 0.51,
                    }
                ],
            },
            "candidate": {
                "candidate_family": "regime_policy",
                "historical": {
                    "replay_live_filled_rows": 23,
                    "replay_attempt_rows": 30,
                    "replay_window_rows": 40,
                },
                "scoring": {
                    "evidence_band": "validated",
                    "validation_live_filled_rows": 23,
                },
            },
        },
        {
            "candidate_family": "global_profile",
            "fill_retention_ratio": 0.84,
            "order_failure_penalty": 0.07,
            "skip_rate_penalty": 0.18,
            "p05_arr_pct": 180000.0,
            "median_arr_pct": 440000.0,
            "p05_arr_delta_pct": 10000.0,
            "median_arr_delta_pct": 20000.0,
            "source": "guardrail_profile",
            "validation_live_filled_rows": 109,
            "runtime_package": {
                "profile": {
                    "name": "grid_d0.00005_up0.48_down0.51",
                    "max_abs_delta": 0.00005,
                    "up_max_buy_price": 0.48,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
            "candidate": {
                "candidate_family": "global_profile",
                "historical": {
                    "replay_live_filled_rows": 109,
                    "replay_attempt_rows": 140,
                    "replay_window_rows": 170,
                },
                "scoring": {
                    "evidence_band": "validated",
                    "validation_live_filled_rows": 109,
                },
            },
        },
    ]

    payload = build_fast_market_search_report(
        autoresearch=autoresearch,
        runtime_truth=_base_runtime_truth_payload(),
        signal_source_audit=_base_signal_source_audit_payload(),
        fastlane_payload=_base_fastlane_payload(),
        edge_scan_payload=_base_edge_scan_payload(),
        generated_at="2026-03-10T16:40:00+00:00",
    )

    ranked = {item["candidate_id"]: item for item in payload["ranked_candidates"]}
    assert "btc5:policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51" not in ranked
    assert "btc5:grid_d0.00005_up0.48_down0.51" in ranked
    assert payload["summary"]["best_runtime_package_id"] == "btc5:grid_d0.00005_up0.48_down0.51"


def test_write_report_artifacts_writes_latest_snapshot_and_history(tmp_path: Path) -> None:
    payload = build_fast_market_search_report(
        autoresearch=_base_autoresearch_payload(),
        runtime_truth=_base_runtime_truth_payload(),
        signal_source_audit=_base_signal_source_audit_payload(),
        fastlane_payload=_base_fastlane_payload(),
        edge_scan_payload=_base_edge_scan_payload(),
        generated_at="2026-03-10T16:30:00+00:00",
    )

    artifacts = write_report_artifacts(
        output_dir=tmp_path / "reports" / "fast_market_search",
        payload=payload,
        stamp="20260310T163000Z",
        history_jsonl=tmp_path / "reports" / "fast_market_search" / "history.jsonl",
    )

    latest_path = Path(artifacts["latest_json"])
    snapshot_path = Path(artifacts["snapshot_json"])
    history_path = Path(artifacts["history_jsonl"])

    assert latest_path.exists()
    assert snapshot_path.exists()
    assert history_path.exists()
    latest_payload = json.loads(latest_path.read_text())
    assert latest_payload["summary"]["best_btc5_candidate_id"] == "btc5:current_live_profile"
    assert len(history_path.read_text().splitlines()) == 1


def test_find_latest_report_recurses_into_nested_runtime_artifact_dirs(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    older = reports_dir / "edge_scan_20260310T010000Z.json"
    nested_newer = reports_dir / "research" / "edge_scan" / "edge_scan_20260310T020000Z.json"
    older.parent.mkdir(parents=True, exist_ok=True)
    nested_newer.parent.mkdir(parents=True, exist_ok=True)
    older.write_text(json.dumps({"generated_at": "2026-03-10T01:00:00+00:00"}) + "\n")
    nested_newer.write_text(json.dumps({"generated_at": "2026-03-10T02:00:00+00:00"}) + "\n")

    selected = _find_latest_report(tmp_path, "edge_scan_*.json")

    assert selected == nested_newer
