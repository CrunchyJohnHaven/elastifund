from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.run_scale_comparison import (
    LaneEvidence,
    TradeOpportunity,
    build_combined_evidence,
    load_or_build_wallet_flow_archive,
    load_wallet_flow_evidence,
    render_markdown,
    run_scale_comparison,
    simulate_lane,
)


def _opportunity(
    signal_id: str,
    direction: str,
    actual_outcome: str,
    timestamp: str = "2026-03-08T00:00:00Z",
    edge: float = 0.30,
    win_probability: float = 0.80,
) -> TradeOpportunity:
    return TradeOpportunity(
        lane="llm_only",
        signal_id=signal_id,
        timestamp=timestamp,
        question=f"Question {signal_id}",
        direction=direction,
        market_price=0.50,
        win_probability=win_probability,
        actual_outcome=actual_outcome,
        edge=edge,
        volume=10000.0,
        liquidity=5000.0,
        kelly_fraction=0.25,
    )


def _write_probe_db(path: Path, rows: list[tuple[int, str, float]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE window_trades (decision_ts INTEGER, order_status TEXT, pnl_usd REAL)"
        )
        conn.executemany(
            "INSERT INTO window_trades(decision_ts, order_status, pnl_usd) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _write_current_probe_payload(
    path: Path,
    *,
    generated_at: str,
    probe_freshness_hours: float,
    trailing_12_pnl_usd: float,
    trailing_40_pnl_usd: float,
    trailing_120_pnl_usd: float,
    order_failed_rate_recent_40: float,
    validation_live_filled_rows: int = 110,
    live_filled_row_count: int = 131,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "deploy_recommendation": "promote",
                "package_confidence_label": "high",
                "validation_live_filled_rows": validation_live_filled_rows,
                "current_probe": {
                    "latest_decision_timestamp": "2026-03-10T15:40:00+00:00",
                    "latest_live_fill_timestamp": "2026-03-10T15:40:00+00:00",
                    "probe_freshness_hours": probe_freshness_hours,
                    "live_filled_row_count": live_filled_row_count,
                    "recent_order_failed_rate": order_failed_rate_recent_40,
                    "trailing_live_filled_windows": {
                        "trailing_12": {
                            "fills": 12,
                            "pnl_usd": trailing_12_pnl_usd,
                            "net_positive": trailing_12_pnl_usd > 0.0,
                        },
                        "trailing_40": {
                            "fills": 40,
                            "pnl_usd": trailing_40_pnl_usd,
                            "net_positive": trailing_40_pnl_usd > 0.0,
                        },
                        "trailing_120": {
                            "fills": 120,
                            "pnl_usd": trailing_120_pnl_usd,
                            "net_positive": trailing_120_pnl_usd > 0.0,
                        },
                    },
                },
            }
        )
    )
    return path


def _write_capital_surface_fixtures(
    tmp_path: Path,
    *,
    runtime_generated_at: str = "2026-03-09T20:51:17+00:00",
    forecast_generated_at: str = "2026-03-09T20:44:44+00:00",
) -> dict[str, Path]:
    runtime_truth_path = tmp_path / "runtime_truth_latest.json"
    runtime_truth_path.write_text(
        json.dumps(
            {
                "generated_at": runtime_generated_at,
                "latest_live_filled_at": "2026-03-09T20:40:00+00:00",
                "btc5_live_filled_rows": 56,
                "btc5_live_filled_pnl_usd": 91.7931,
                "btc5_recent_live_filled_rows": 12,
                "btc5_recent_live_filled_pnl_usd": 22.5799,
                "launch": {
                    "blocked_checks": [
                        "polymarket_capital_truth_drift",
                        "accounting_reconciliation_drift",
                    ]
                },
                "state_improvement": {
                    "strategy_recommendations": {
                        "public_performance_scoreboard": {
                            "deploy_recommendation": "promote",
                            "forecast_confidence_label": "high",
                            "realized_btc5_sleeve_window_pnl_usd": 22.5799,
                            "realized_btc5_sleeve_window_live_fills": 12,
                            "realized_btc5_sleeve_window_hours": 2.4167,
                        }
                    }
                },
            }
        )
    )
    public_runtime_snapshot_path = tmp_path / "public_runtime_snapshot.json"
    public_runtime_snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": runtime_generated_at,
                "state_improvement": {
                    "strategy_recommendations": {
                        "public_performance_scoreboard": {
                            "deploy_recommendation": "promote",
                            "forecast_confidence_label": "high",
                            "realized_btc5_sleeve_window_pnl_usd": 22.5799,
                            "realized_btc5_sleeve_window_live_fills": 12,
                            "realized_btc5_sleeve_window_hours": 2.4167,
                        }
                    }
                },
            }
        )
    )
    btc5_autoresearch_path = tmp_path / "btc5_latest.json"
    btc5_autoresearch_path.write_text(
        json.dumps(
            {
                "generated_at": forecast_generated_at,
                "deploy_recommendation": "promote",
                "package_confidence_label": "high",
                "public_forecast_selection": {
                    "selected": {
                        "generated_at": forecast_generated_at,
                        "deploy_recommendation": "promote",
                        "package_confidence_label": "high",
                        "validation_live_filled_rows": 41,
                    }
                },
            }
        )
    )
    kalshi_weather_lane_path = tmp_path / "instance05_weather_lane.json"
    kalshi_weather_lane_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T19:08:35+00:00",
                "recommended_strategy": "binary_threshold",
                "robustness_summary": {
                    "binary_threshold": {
                        "scenario_count": 9,
                        "positive_scenario_ratio": 0.7778,
                        "median_total_pnl_usd": 90.3304,
                    }
                },
                "settlement_reconciliation": {
                    "matched_settlements": 0,
                    "unmatched_settlements": 0,
                    "match_rate": 0.0,
                },
                "operator_guidance": {"paper_trade_parameters": {"mode": "paper"}},
            }
        )
    )
    kalshi_orders_path = tmp_path / "kalshi_weather_orders.jsonl"
    kalshi_orders_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-09T10:51:47+00:00",
                        "order": {"ticker": "KAL-1", "side": "yes", "status": "live"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-09T10:51:48+00:00",
                        "order": {"ticker": "KAL-2", "side": "no", "status": "paper"},
                    }
                ),
            ]
        )
        + "\n"
    )
    return {
        "runtime_truth_path": runtime_truth_path,
        "public_runtime_snapshot_path": public_runtime_snapshot_path,
        "btc5_autoresearch_path": btc5_autoresearch_path,
        "kalshi_weather_lane_path": kalshi_weather_lane_path,
        "kalshi_orders_path": kalshi_orders_path,
    }


def _write_ready_signal_audit(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T12:59:00+00:00",
                "btc_fast_window_confirmation": {
                    "status": "ready",
                    "summary": {
                        "ready_sources": ["wallet_flow"],
                        "best_source_by_confirmation_lift": "wallet_flow",
                        "confirmation_coverage_ratio": 0.75,
                        "confirmation_resolved_window_coverage": 0.75,
                        "confirmation_executed_window_coverage": 0.5,
                        "confirmation_false_suppression_cost_usd": 0.25,
                        "confirmation_lift_avg_pnl_usd": 1.8,
                        "confirmation_lift_win_rate": 0.2,
                        "confirmation_contradiction_penalty": 0.1,
                        "confirmation_coverage_label": "strong",
                        "confirmation_strength_label": "strong",
                        "confirmation_strength_score": 0.6925,
                    },
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "supports_capital_allocation": True,
                    "wallet_flow_confirmation_ready": True,
                    "wallet_flow_archive_confirmation_ready": True,
                    "lmsr_archive_confirmation_ready": False,
                    "btc_fast_window_confirmation_ready": True,
                    "confirmation_support_status": "ready",
                    "confirmation_sources_ready": ["wallet_flow"],
                    "best_confirmation_source": "wallet_flow",
                    "confirmation_coverage_ratio": 0.75,
                    "confirmation_resolved_window_coverage": 0.75,
                    "confirmation_executed_window_coverage": 0.5,
                    "confirmation_false_suppression_cost_usd": 0.25,
                    "confirmation_lift_avg_pnl_usd": 1.8,
                    "confirmation_lift_win_rate": 0.2,
                    "confirmation_contradiction_penalty": 0.1,
                    "confirmation_coverage_label": "strong",
                    "confirmation_strength_label": "strong",
                    "confirmation_strength_score": 0.6925,
                    "confirmation_blocking_checks": [],
                    "capital_expansion_support_status": "ready",
                    "stage_upgrade_support_status": "ready",
                    "stage_upgrade_blocking_checks": [],
                    "best_component_source": "wallet_flow",
                    "best_source_combo": "llm+wallet_flow",
                },
                "wallet_flow_vs_llm": {
                    "status": "ready",
                    "winner": "wallet_flow",
                    "wallet_flow_any_win_rate_delta_vs_llm_only": 0.05,
                },
                "combined_sources_vs_single_source": {
                    "status": "ready",
                    "winner": "combined",
                    "combined_sources_beat_single_source_lanes": True,
                },
                "ranking_snapshot": {
                    "best_component_source": {"source": "wallet_flow", "win_rate": 0.62},
                    "best_source_combo": {"source_combo": "llm+wallet_flow", "win_rate": 0.70},
                },
            }
        )
    )
    return path


def _write_limited_signal_audit(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T12:59:00+00:00",
                "btc_fast_window_confirmation": {
                    "status": "insufficient_data",
                    "summary": {
                        "ready_sources": [],
                        "best_source_by_confirmation_lift": None,
                        "confirmation_coverage_ratio": None,
                        "confirmation_resolved_window_coverage": None,
                        "confirmation_executed_window_coverage": None,
                        "confirmation_false_suppression_cost_usd": None,
                        "confirmation_lift_avg_pnl_usd": None,
                        "confirmation_lift_win_rate": None,
                        "confirmation_contradiction_penalty": None,
                        "confirmation_coverage_label": "missing",
                        "confirmation_strength_label": "missing",
                        "confirmation_strength_score": 0.0,
                    },
                    "missing_requirements": [
                        "wallet_flow:source_window_rows 0 < required 3",
                    ],
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "insufficient_data",
                    "combined_sources_vs_single_source_status": "insufficient_data",
                    "supports_capital_allocation": False,
                    "wallet_flow_confirmation_ready": False,
                    "wallet_flow_archive_confirmation_ready": False,
                    "lmsr_archive_confirmation_ready": False,
                    "btc_fast_window_confirmation_ready": False,
                    "confirmation_support_status": "limited",
                    "confirmation_sources_ready": [],
                    "best_confirmation_source": None,
                    "confirmation_coverage_ratio": None,
                    "confirmation_resolved_window_coverage": None,
                    "confirmation_executed_window_coverage": None,
                    "confirmation_false_suppression_cost_usd": None,
                    "confirmation_lift_avg_pnl_usd": None,
                    "confirmation_lift_win_rate": None,
                    "confirmation_contradiction_penalty": None,
                    "confirmation_coverage_label": "missing",
                    "confirmation_strength_label": "missing",
                    "confirmation_strength_score": 0.0,
                    "confirmation_blocking_checks": [
                        "wallet_flow:source_window_rows 0 < required 3",
                    ],
                    "capital_expansion_support_status": "blocked",
                    "stage_upgrade_support_status": "limited",
                    "stage_upgrade_blocking_checks": ["wallet_flow_vs_llm_not_ready"],
                    "best_component_source": "llm",
                    "best_source_combo": None,
                },
                "wallet_flow_vs_llm": {
                    "status": "insufficient_data",
                    "winner": None,
                    "wallet_flow_any_win_rate_delta_vs_llm_only": None,
                },
            }
        )
    )
    return path


def _write_negative_confirmation_signal_audit(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T12:59:00+00:00",
                "btc_fast_window_confirmation": {
                    "status": "ready",
                    "summary": {
                        "ready_sources": ["wallet_flow"],
                        "best_source_by_confirmation_lift": "wallet_flow",
                        "confirmation_coverage_ratio": 1.0,
                        "confirmation_resolved_window_coverage": 1.0,
                        "confirmation_executed_window_coverage": 1.0,
                        "confirmation_false_suppression_cost_usd": 6.0,
                        "confirmation_lift_avg_pnl_usd": -1.5,
                        "confirmation_lift_win_rate": -0.2,
                        "confirmation_contradiction_penalty": 0.8,
                        "confirmation_coverage_label": "strong",
                        "confirmation_strength_label": "weak",
                        "confirmation_strength_score": 0.44,
                    },
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "supports_capital_allocation": True,
                    "wallet_flow_confirmation_ready": True,
                    "wallet_flow_archive_confirmation_ready": True,
                    "lmsr_archive_confirmation_ready": False,
                    "btc_fast_window_confirmation_ready": True,
                    "confirmation_support_status": "ready",
                    "confirmation_sources_ready": ["wallet_flow"],
                    "best_confirmation_source": "wallet_flow",
                    "confirmation_coverage_ratio": 1.0,
                    "confirmation_resolved_window_coverage": 1.0,
                    "confirmation_executed_window_coverage": 1.0,
                    "confirmation_false_suppression_cost_usd": 6.0,
                    "confirmation_lift_avg_pnl_usd": -1.5,
                    "confirmation_lift_win_rate": -0.2,
                    "confirmation_contradiction_penalty": 0.8,
                    "confirmation_coverage_label": "strong",
                    "confirmation_strength_label": "weak",
                    "confirmation_strength_score": 0.44,
                    "confirmation_blocking_checks": [],
                    "capital_expansion_support_status": "ready",
                    "stage_upgrade_support_status": "ready",
                    "stage_upgrade_blocking_checks": [],
                    "best_component_source": "wallet_flow",
                    "best_source_combo": "llm+wallet_flow",
                },
                "wallet_flow_vs_llm": {
                    "status": "ready",
                    "winner": "wallet_flow",
                    "wallet_flow_any_win_rate_delta_vs_llm_only": 0.05,
                },
                "combined_sources_vs_single_source": {
                    "status": "ready",
                    "winner": "combined",
                    "combined_sources_beat_single_source_lanes": True,
                },
                "ranking_snapshot": {
                    "best_component_source": {"source": "wallet_flow", "win_rate": 0.62},
                    "best_source_combo": {"source_combo": "llm+wallet_flow", "win_rate": 0.70},
                },
            }
        )
    )
    return path


def _write_weak_coverage_signal_audit(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T12:59:00+00:00",
                "btc_fast_window_confirmation": {
                    "status": "ready",
                    "summary": {
                        "ready_sources": ["wallet_flow"],
                        "best_source_by_confirmation_lift": "wallet_flow",
                        "confirmation_coverage_ratio": 0.40,
                        "confirmation_resolved_window_coverage": 0.40,
                        "confirmation_executed_window_coverage": 0.25,
                        "confirmation_false_suppression_cost_usd": 0.2,
                        "confirmation_false_confirmation_cost_usd": 0.1,
                        "confirmation_lift_avg_pnl_usd": 0.8,
                        "confirmation_lift_win_rate": 0.08,
                        "confirmation_contradiction_penalty": 0.1,
                        "confirmation_coverage_label": "weak",
                        "confirmation_strength_label": "weak",
                        "confirmation_strength_score": 0.3245,
                    },
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "supports_capital_allocation": True,
                    "wallet_flow_confirmation_ready": True,
                    "wallet_flow_archive_confirmation_ready": True,
                    "lmsr_archive_confirmation_ready": False,
                    "btc_fast_window_confirmation_ready": True,
                    "confirmation_support_status": "ready",
                    "confirmation_sources_ready": ["wallet_flow"],
                    "best_confirmation_source": "wallet_flow",
                    "confirmation_coverage_ratio": 0.40,
                    "confirmation_resolved_window_coverage": 0.40,
                    "confirmation_executed_window_coverage": 0.25,
                    "confirmation_false_suppression_cost_usd": 0.2,
                    "confirmation_false_confirmation_cost_usd": 0.1,
                    "confirmation_lift_avg_pnl_usd": 0.8,
                    "confirmation_lift_win_rate": 0.08,
                    "confirmation_contradiction_penalty": 0.1,
                    "confirmation_coverage_label": "weak",
                    "confirmation_strength_label": "weak",
                    "confirmation_strength_score": 0.3245,
                    "confirmation_blocking_checks": [],
                    "capital_expansion_support_status": "ready",
                    "stage_upgrade_support_status": "ready",
                    "stage_upgrade_blocking_checks": [],
                    "best_component_source": "wallet_flow",
                    "best_source_combo": "llm+wallet_flow",
                },
                "wallet_flow_vs_llm": {
                    "status": "ready",
                    "winner": "wallet_flow",
                    "wallet_flow_any_win_rate_delta_vs_llm_only": 0.05,
                },
                "combined_sources_vs_single_source": {
                    "status": "ready",
                    "winner": "combined",
                    "combined_sources_beat_single_source_lanes": True,
                },
                "ranking_snapshot": {
                    "best_component_source": {"source": "wallet_flow", "win_rate": 0.62},
                    "best_source_combo": {"source_combo": "llm+wallet_flow", "win_rate": 0.70},
                },
            }
        )
    )
    return path


def _write_capacity_stress_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T12:58:00+00:00",
                "capacity_stress_summary": {
                    "metric_name": "capacity_stress_summary",
                    "recommended_reference": "best_candidate",
                    "profiles": {
                        "best_candidate": {
                            "profile_name": "best_candidate",
                            "size_sweeps": [
                                {
                                    "trade_size_usd": 10.0,
                                    "expected_fill_retention_ratio": 0.9,
                                    "expected_profit_probability": 0.74,
                                    "expected_loss_hit_probability": 0.08,
                                    "expected_median_arr_pct": 200.0,
                                    "expected_p05_arr_pct": 50.0,
                                    "expected_p95_max_drawdown_usd": 12.0,
                                },
                                {
                                    "trade_size_usd": 100.0,
                                    "expected_fill_retention_ratio": 0.42,
                                    "expected_fill_probability": 0.55,
                                    "expected_order_failed_probability": 0.31,
                                    "expected_post_only_retry_failure_rate": 0.27,
                                    "expected_profit_probability": 0.68,
                                    "expected_loss_limit_hit_probability": 0.11,
                                    "expected_median_arr_pct": 420.0,
                                    "expected_p05_arr_pct": 80.0,
                                    "expected_p95_max_drawdown_usd": 35.0,
                                },
                                {
                                    "trade_size_usd": 300.0,
                                    "expected_fill_retention_ratio": 0.12,
                                    "expected_fill_probability": 0.19,
                                    "expected_order_failed_probability": 0.54,
                                    "expected_post_only_retry_failure_rate": 0.47,
                                    "expected_profit_probability": 0.61,
                                    "expected_loss_limit_hit_probability": 0.18,
                                    "expected_median_arr_pct": 510.0,
                                    "expected_p05_arr_pct": -40.0,
                                    "expected_p95_max_drawdown_usd": 140.0,
                                },
                            ],
                            "shadow_trade_size_assessments": [
                                {
                                    "shadow_label": "shadow_100",
                                    "trade_size_usd": 100.0,
                                    "status": "shadow_blocked",
                                    "deployment_class": "blocked",
                                    "blocking_categories": ["missing_truth", "execution_quality"],
                                    "blocking_reasons": [
                                        "higher_notional_live_validation_missing",
                                        "order_failed_probability_above_0.25",
                                        "post_only_retry_failure_rate_above_0.20",
                                    ],
                                    "evidence_required": [
                                        "Replay higher-notional BTC5 windows in live truth before promotion.",
                                        "Reduce post-only retry failures and order-failed drag at the target ticket size.",
                                    ],
                                    "evidence_verdict": "mixed_missing_and_true_negative",
                                    "missing_evidence_items": ["higher_notional_live_validation_missing"],
                                    "true_negative_items": ["post_only_execution_quality_below_threshold"],
                                    "execution_drag_summary": {
                                        "fill_retention_ratio": 0.42,
                                        "order_failed_probability": 0.31,
                                        "post_only_retry_failure_rate": 0.27,
                                    },
                                    "tail_risk_summary": {
                                        "daily_loss_hit_probability": 0.11,
                                        "p95_drawdown_usd": 35.0,
                                    },
                                    "expected_fill_probability": 0.55,
                                    "expected_fill_retention_ratio": 0.42,
                                    "expected_order_failed_probability": 0.31,
                                    "expected_post_only_retry_failure_rate": 0.27,
                                    "expected_profit_probability": 0.68,
                                    "expected_loss_limit_hit_probability": 0.11,
                                    "expected_p05_arr_pct": 80.0,
                                    "expected_p95_max_drawdown_usd": 35.0,
                                },
                                {
                                    "shadow_label": "shadow_300",
                                    "trade_size_usd": 300.0,
                                    "status": "shadow_blocked",
                                    "deployment_class": "blocked",
                                    "blocking_categories": [
                                        "missing_truth",
                                        "liquidity",
                                        "execution_quality",
                                        "drawdown_tails",
                                    ],
                                    "blocking_reasons": [
                                        "higher_notional_live_validation_missing",
                                        "fill_retention_below_0.25",
                                        "order_failed_probability_above_0.25",
                                        "post_only_retry_failure_rate_above_0.20",
                                        "p05_arr_non_positive",
                                        "p95_drawdown_above_shadow_ceiling",
                                    ],
                                    "evidence_required": [
                                        "Replay higher-notional BTC5 windows in live truth before promotion.",
                                        "Improve fill retention at the target ticket size with session-aware concentration.",
                                        "Reduce post-only retry failures and order-failed drag at the target ticket size.",
                                        "Improve stressed tail metrics before promotion.",
                                    ],
                                    "evidence_verdict": "mixed_missing_and_true_negative",
                                    "missing_evidence_items": ["higher_notional_live_validation_missing"],
                                    "true_negative_items": [
                                        "fill_retention_below_threshold",
                                        "post_only_execution_quality_below_threshold",
                                        "tail_risk_below_threshold",
                                    ],
                                    "execution_drag_summary": {
                                        "fill_retention_ratio": 0.12,
                                        "order_failed_probability": 0.54,
                                        "post_only_retry_failure_rate": 0.47,
                                    },
                                    "tail_risk_summary": {
                                        "daily_loss_hit_probability": 0.18,
                                        "p95_drawdown_usd": 140.0,
                                    },
                                    "expected_fill_probability": 0.19,
                                    "expected_fill_retention_ratio": 0.12,
                                    "expected_order_failed_probability": 0.54,
                                    "expected_post_only_retry_failure_rate": 0.47,
                                    "expected_profit_probability": 0.61,
                                    "expected_loss_limit_hit_probability": 0.18,
                                    "expected_p05_arr_pct": -40.0,
                                    "expected_p95_max_drawdown_usd": 140.0,
                                },
                            ],
                        }
                    },
                },
            }
        )
    )
    return path


def _probe_rows(*, live_filled: int, failed: int = 0, start_ts: int = 1773136800) -> list[tuple[int, str, float]]:
    rows: list[tuple[int, str, float]] = []
    decision_ts = start_ts
    for _ in range(live_filled):
        rows.append((decision_ts, "live_filled", 1.5))
        decision_ts -= 300
    for _ in range(failed):
        rows.append((decision_ts, "live_order_failed", 0.0))
        decision_ts -= 300
    return rows
