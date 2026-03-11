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
                    },
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "supports_capital_allocation": True,
                    "wallet_flow_confirmation_ready": True,
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
                    },
                },
                "capital_ranking_support": {
                    "audit_generated_at": "2026-03-10T12:59:00+00:00",
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "supports_capital_allocation": True,
                    "wallet_flow_confirmation_ready": True,
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
                                    "expected_profit_probability": 0.68,
                                    "expected_loss_hit_probability": 0.11,
                                    "expected_median_arr_pct": 420.0,
                                    "expected_p05_arr_pct": 80.0,
                                    "expected_p95_max_drawdown_usd": 35.0,
                                },
                                {
                                    "trade_size_usd": 200.0,
                                    "expected_fill_retention_ratio": 0.24,
                                    "expected_profit_probability": 0.61,
                                    "expected_loss_hit_probability": 0.17,
                                    "expected_median_arr_pct": 510.0,
                                    "expected_p05_arr_pct": 40.0,
                                    "expected_p95_max_drawdown_usd": 72.0,
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


def test_simulate_lane_uses_conservative_caps():
    result = simulate_lane(
        [
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "YES_WON"),
        ],
        bankroll=1000.0,
    )

    assert result["status"] == "simulated"
    assert result["trade_count"] == 2
    assert result["attempted_trades"] == 2
    assert result["wins"] == 1
    assert result["total_turnover_usd"] == 10.0
    assert result["capital_utilization_pct"] > 0.0
    assert result["fee_drag_pct"] > 0.0
    assert result["max_drawdown_usd"] > 0.0


def test_build_combined_evidence_only_includes_ready_lanes():
    evidences = {
        "llm_only": LaneEvidence(
            lane="llm_only",
            status="ready",
            opportunities=[_opportunity("1", "buy_yes", "YES_WON")],
            assumptions=["llm assumption"],
            evidence_summary={"qualified_signals": 1},
        ),
        "wallet_flow": LaneEvidence(
            lane="wallet_flow",
            status="insufficient_data",
            reasons=["zero signals"],
            evidence_summary={"resolved_qualifying_signals": 0},
        ),
    }

    combined = build_combined_evidence(evidences)

    assert combined.status == "ready"
    assert len(combined.opportunities) == 1
    assert combined.evidence_summary["included_lanes"] == ["llm_only"]
    assert combined.evidence_summary["excluded_lanes"] == ["wallet_flow"]


def test_run_scale_comparison_writes_reports(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 9, 21, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        assumptions=["synthetic llm lane"],
        evidence_summary={"qualified_signals": 2},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-08T00:05:00Z"),
        ],
    )
    insufficient = LaneEvidence(
        lane="wallet_flow",
        status="insufficient_data",
        reasons=["zero qualifying signals"],
        evidence_summary={"resolved_qualifying_signals": 0},
    )

    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": insufficient,
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )

    json_path = tmp_path / "strategy_scale_comparison.json"
    markdown_path = tmp_path / "strategy_scale_comparison.md"
    runtime_truth_path = tmp_path / "runtime_truth_latest.json"
    runtime_truth_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T20:51:17+00:00",
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
                "generated_at": "2026-03-09T20:51:17+00:00",
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
                "generated_at": "2026-03-09T20:44:44+00:00",
                "deploy_recommendation": "promote",
                "package_confidence_label": "high",
                "public_forecast_selection": {
                    "selected": {
                        "generated_at": "2026-03-09T20:44:44+00:00",
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
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 6:00AM-6:05AM ET","Buy","5.0","10.0","Down","1773070500","0x1"',
                '"Bitcoin Up or Down - March 10, 6:00AM-6:05AM ET","Redeem","0","0","","1773073800","0x2"',
                '"Bitcoin Up or Down - March 10, 6:05AM-6:10AM ET","Buy","5.0","10.4","Up","1773070800","0x3"',
                '"Bitcoin Up or Down - March 10, 6:05AM-6:10AM ET","Redeem","0","0","","1773074100","0x4"',
                '"Will Harvey Weinstein be sentenced to no prison time?","Buy","43.1032","100","Yes","1773073500","0x5"',
                '"Deposited funds","Deposit","247.505808","247.505808","USDC","1772885033","0x6"',
            ]
        )
        + "\n"
    )
    signal_source_audit_path = _write_ready_signal_audit(tmp_path / "signal_source_audit.json")
    btc5_monte_carlo_path = _write_capacity_stress_fixture(tmp_path / "btc5_monte_carlo_latest.json")
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(probe_db_path, _probe_rows(live_filled=12, failed=2))

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=json_path,
        markdown_output_path=markdown_path,
        signal_source_audit_path=signal_source_audit_path,
        runtime_truth_path=runtime_truth_path,
        public_runtime_snapshot_path=public_runtime_snapshot_path,
        btc5_autoresearch_path=btc5_autoresearch_path,
        btc5_monte_carlo_path=btc5_monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_weather_lane_path=kalshi_weather_lane_path,
        kalshi_orders_path=kalshi_orders_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
    )

    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text())
    assert payload["results"]["llm_only"]["1000"]["status"] == "simulated"
    assert payload["results"]["wallet_flow"]["1000"]["status"] == "insufficient_data"
    assert payload["results"]["combined"]["1000"]["status"] == "simulated"
    assert payload["lane_evidence"]["combined"]["evidence_summary"]["included_lanes"] == ["llm_only"]
    assert payload["scoreboard"]["llm_only"]["confidence_label"] == "low"
    assert payload["scoreboard"]["llm_only"]["deployment_readiness"] == "research_candidate"
    assert payload["scoreboard"]["llm_only"]["sample_size_summary"]["replayable_opportunities"] == 2
    assert payload["scoreboard"]["llm_only"]["sample_size_summary"]["unique_markets"] == 2
    assert payload["scoreboard"]["llm_only"]["sample_size_summary"]["resolved_signals"] == 2
    assert payload["scoreboard"]["llm_only"]["timebound_evidence_window"]["status"] == "ready"
    assert payload["scoreboard"]["wallet_flow"]["deployment_readiness"] == "insufficient_data"
    assert payload["source_audit"]["loaded"] is True
    assert payload["source_audit"]["btc_fast_window_confirmation"]["status"] == "ready"
    assert payload["ranking"]
    assert payload["ranking"][0]["lane"] in {"combined", "llm_only"}
    assert payload["venue_scoreboard"][0]["venue"] == "polymarket"
    assert payload["venue_scoreboard"][0]["lane"] == "btc5"
    assert payload["venue_scoreboard"][0]["capital_status"] == "ready_scale"
    assert payload["venue_scoreboard"][0]["capital_efficiency_score"] > 0
    assert payload["venue_scoreboard"][0]["stage_readiness"]["recommended_stage"] == 1
    assert payload["venue_scoreboard"][0]["wallet_export_summary"]["btc_closed_markets"] == 2
    assert payload["venue_scoreboard"][0]["confirmation_support"]["status"] == "ready"
    assert payload["venue_scoreboard"][0]["confirmation_support"]["best_source"] == "wallet_flow"
    assert payload["venue_scoreboard"][0]["confirmation_support"]["coverage_ratio"] == 0.75
    assert payload["venue_scoreboard"][0]["confirmation_support"]["executed_window_coverage"] == 0.5
    assert payload["venue_scoreboard"][0]["confirmation_support"]["false_suppression_cost_usd"] == 0.25
    assert payload["venue_scoreboard"][1]["venue"] == "kalshi"
    assert payload["venue_scoreboard"][1]["capital_status"] == "hold"
    assert payload["venue_scoreboard"][1]["settlement_match_rate"] == 0.0
    assert payload["next_100_usd"]["venue"] == "polymarket"
    assert payload["next_1000_usd"]["venue"] == "polymarket"
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["venue"] == "polymarket"
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["lane"] == "btc5"
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["recommended_amount_usd"] == 100
    assert payload["capital_allocation_recommendation"]["next_1000_usd"]["status"] == "ready_scale"
    assert payload["capital_allocation_recommendation"]["next_1000_usd"]["recommended_amount_usd"] == 1000
    assert payload["capital_allocation_recommendation"]["next_100_shadow"]["status"] == "shadow_only"
    assert payload["capital_allocation_recommendation"]["next_100_shadow"]["trade_size_usd"] == 100.0
    assert payload["capital_allocation_recommendation"]["next_200_shadow"]["status"] == "shadow_only"
    assert payload["next_100_shadow"]["status"] == "shadow_only"
    assert payload["next_200_shadow"]["status"] == "shadow_only"
    assert payload["capital_allocation_recommendation"]["stage_readiness"]["recommended_stage"] == 1

    markdown = markdown_path.read_text()
    assert "Strategy Scale Comparison" in markdown
    assert "Lane Scoreboard" in markdown
    assert "Venue Capital Scoreboard" in markdown
    assert "Where should the next $100 go?" in markdown
    assert "Where should the next $1,000 go?" in markdown
    assert "What should stay shadow-only at $100 trade size?" in markdown
    assert "wallet_flow" in markdown
    assert "shadow-only" in markdown


def test_run_scale_comparison_holds_when_wallet_export_is_stale(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 11, 21, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 1},
        opportunities=[_opportunity("1", "buy_yes", "YES_WON")],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(tmp_path)
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 9, 6:00AM-6:05AM ET","Buy","5.0","10.0","Down","1772984100","0x1"',
                '"Bitcoin Up or Down - March 9, 6:00AM-6:05AM ET","Redeem","0","0","","1772987400","0x2"',
            ]
        )
        + "\n"
    )

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "strategy_scale_comparison.json",
        markdown_output_path=tmp_path / "strategy_scale_comparison.md",
        signal_source_audit_path=tmp_path / "missing_signal_source_audit.json",
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=tmp_path / "missing_btc5_probe.db",
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    btc5_entry = next(item for item in report["venue_scoreboard"] if item["venue"] == "polymarket")
    assert btc5_entry["capital_status"] == "hold"
    assert btc5_entry["stage_readiness"]["recommended_stage"] == 0
    assert "wallet_export_stale" in btc5_entry["blocking_checks"]
    assert report["next_100_usd"]["status"] == "hold"
    assert report["next_1000_usd"]["status"] == "hold"


def test_run_scale_comparison_surfaces_stale_probe_for_stage_upgrades(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 1},
        opportunities=[_opportunity("1", "buy_yes", "YES_WON")],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(tmp_path, forecast_generated_at="2026-03-10T17:30:00+00:00")
    audit_path = _write_ready_signal_audit(tmp_path / "signal_source_audit.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 1:00PM-1:05PM ET","Buy","5.0","10.0","Down","1773165600","0x1"',
                '"Bitcoin Up or Down - March 10, 1:00PM-1:05PM ET","Redeem","0","0","","1773165900","0x2"',
            ]
        )
        + "\n"
    )
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(
        probe_db_path,
        _probe_rows(live_filled=12, failed=2, start_ts=1773136800),
    )

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "strategy_scale_comparison.json",
        markdown_output_path=tmp_path / "strategy_scale_comparison.md",
        signal_source_audit_path=audit_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    btc5_entry = next(item for item in report["venue_scoreboard"] if item["venue"] == "polymarket")
    assert btc5_entry["capital_status"] == "hold"
    assert btc5_entry["stage_readiness"]["recommended_stage"] == 0
    assert "stage_upgrade_probe_stale" in btc5_entry["blocking_checks"]
    assert btc5_entry["freshness_hours"] == 8.0
    assert report["next_100_usd"]["status"] == "hold"
    assert report["next_1000_usd"]["status"] == "hold"
    assert report["next_1000_usd"]["stage_gate_reason"].startswith("No capital stage is eligible yet.")


def test_run_scale_comparison_prefers_current_probe_latest_over_stale_probe_db(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 16, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 1},
        opportunities=[_opportunity("1", "buy_yes", "YES_WON")],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(
        tmp_path,
        runtime_generated_at="2026-03-10T15:55:00+00:00",
        forecast_generated_at="2026-03-10T15:54:00+00:00",
    )
    audit_path = _write_ready_signal_audit(tmp_path / "signal_source_audit.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 10:35AM-10:40AM ET","Buy","5.0","10.0","Down","1773156900","0x1"',
                '"Bitcoin Up or Down - March 10, 10:35AM-10:40AM ET","Redeem","0","0","","1773157200","0x2"',
            ]
        )
        + "\n"
    )
    stale_probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(
        stale_probe_db_path,
        _probe_rows(live_filled=120, failed=3, start_ts=1773136800),
    )
    current_probe_path = _write_current_probe_payload(
        tmp_path / "btc5_current_probe_latest.json",
        generated_at="2026-03-10T15:59:00+00:00",
        probe_freshness_hours=0.35,
        trailing_12_pnl_usd=-29.3863,
        trailing_40_pnl_usd=-34.5164,
        trailing_120_pnl_usd=93.5718,
        order_failed_rate_recent_40=0.175,
    )

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "strategy_scale_comparison.json",
        markdown_output_path=tmp_path / "strategy_scale_comparison.md",
        signal_source_audit_path=audit_path,
        wallet_export_path=wallet_export_path,
        btc5_current_probe_path=current_probe_path,
        btc5_probe_db_path=stale_probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    btc5_entry = next(item for item in report["venue_scoreboard"] if item["venue"] == "polymarket")
    assert btc5_entry["probe_summary"]["source"] == "current_probe_latest"
    assert btc5_entry["stage_readiness"]["fresh_probe_summary"] is True
    assert btc5_entry["stage_readiness"]["probe_freshness_hours"] == 0.35
    assert btc5_entry["stage_readiness"]["recommended_stage"] == 0
    assert "stage_upgrade_probe_stale" not in btc5_entry["stage_readiness"]["blocking_checks"]
    assert "trailing_12_live_filled_not_positive" in btc5_entry["stage_readiness"]["blocking_checks"]
    assert report["capital_allocation_recommendation"]["stage_readiness"]["probe_freshness_hours"] == 0.35


def test_run_scale_comparison_holds_when_signal_audit_blocks_capital_expansion(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 2},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-10T12:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(
        tmp_path,
        runtime_generated_at="2026-03-10T12:55:00+00:00",
        forecast_generated_at="2026-03-10T12:54:00+00:00",
    )
    audit_path = _write_limited_signal_audit(tmp_path / "signal_source_audit.json")
    monte_carlo_path = _write_capacity_stress_fixture(tmp_path / "btc5_monte_carlo_latest.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Buy","5.0","10.0","Down","1773137400","0x1"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Redeem","0","0","","1773137700","0x2"',
            ]
        )
        + "\n"
    )
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(probe_db_path, _probe_rows(live_filled=12, failed=2, start_ts=1773147300))

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "strategy_scale_comparison.json",
        markdown_output_path=tmp_path / "strategy_scale_comparison.md",
        signal_source_audit_path=audit_path,
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    btc5_entry = next(item for item in report["venue_scoreboard"] if item["venue"] == "polymarket")
    assert btc5_entry["stage_readiness"]["recommended_stage"] == 1
    assert btc5_entry["capital_status"] == "hold"
    assert "wallet_flow_vs_llm_not_ready" in btc5_entry["blocking_checks"]
    assert btc5_entry["audit_support"]["supports_live_capital_expansion"] is False
    assert report["next_100_usd"]["status"] == "hold"
    assert report["next_1000_usd"]["status"] == "hold"
    assert report["next_100_shadow"]["status"] == "shadow_only"
    assert report["next_200_shadow"]["status"] == "shadow_only"


def test_render_markdown_mentions_combined_included_lanes():
    report = {
        "generated_at": "2026-03-08T00:00:00+00:00",
        "as_of_date": "2026-03-08",
        "bankrolls": [1000],
        "risk_caps": {
            "max_position_usd": 5.0,
            "llm_kelly_fraction": 0.25,
            "fast_kelly_fraction": 0.0625,
            "max_allocation_pct": 0.20,
        },
        "execution_assumptions": {
            "simulator_mode": "taker",
            "entry_price_baseline_llm": 0.50,
        },
        "lane_evidence": {
            "llm_only": {
                "status": "ready",
                "reasons": [],
                "assumptions": ["llm assumption"],
                "evidence_summary": {"qualified_signals": 2},
            },
            "wallet_flow": {
                "status": "insufficient_data",
                "reasons": ["zero signals"],
                "assumptions": [],
                "evidence_summary": {"resolved_qualifying_signals": 0},
            },
            "lmsr": {
                "status": "insufficient_data",
                "reasons": ["missing archive"],
                "assumptions": [],
                "evidence_summary": {},
            },
            "cross_platform_arb": {
                "status": "insufficient_data",
                "reasons": ["missing archive"],
                "assumptions": [],
                "evidence_summary": {},
            },
            "combined": {
                "status": "ready",
                "reasons": [],
                "assumptions": ["combined assumption"],
                "evidence_summary": {"included_lanes": ["llm_only"], "excluded_lanes": ["wallet_flow"]},
            },
        },
        "results": {
            "llm_only": {
                "1000": {
                    "status": "simulated",
                    "return_pct": 0.10,
                    "max_drawdown_pct": 0.02,
                    "max_drawdown_usd": 20.0,
                    "trade_count": 5,
                    "capital_utilization_pct": 0.005,
                    "fee_drag_pct": 0.04,
                }
            },
            "wallet_flow": {"1000": {"status": "insufficient_data", "reasons": ["zero signals"]}},
            "lmsr": {"1000": {"status": "insufficient_data", "reasons": ["missing archive"]}},
            "cross_platform_arb": {"1000": {"status": "insufficient_data", "reasons": ["missing archive"]}},
            "combined": {
                "1000": {
                    "status": "simulated",
                    "return_pct": 0.10,
                    "max_drawdown_pct": 0.02,
                    "max_drawdown_usd": 20.0,
                    "trade_count": 5,
                    "capital_utilization_pct": 0.005,
                    "fee_drag_pct": 0.04,
                }
            },
        },
        "scoreboard": {
            "llm_only": {
                "status": "ready",
                "confidence_label": "low",
                "deployment_readiness": "research_candidate",
                "ranking_score": 0.03,
                "sample_size_summary": {
                    "replayable_opportunities": 2,
                    "unique_markets": 2,
                    "resolved_signals": 2,
                },
                "timebound_evidence_window": {
                    "status": "ready",
                    "source_class": "replayable_opportunities",
                    "start": "2026-03-08T00:00:00+00:00",
                    "end": "2026-03-08T00:05:00+00:00",
                    "elapsed_hours": 0.083333,
                    "observation_count": 2,
                },
                "median_return_pct": 0.10,
                "p05_return_pct": 0.10,
                "max_drawdown_pct": 0.02,
                "source_evidence": {
                    "wallet_flow_beats_llm_only": None,
                    "combined_sources_beat_single_source_lanes": None,
                    "lane_source_status": "unknown",
                },
            },
            "wallet_flow": {
                "status": "insufficient_data",
                "confidence_label": "low",
                "deployment_readiness": "insufficient_data",
                "ranking_score": None,
                "sample_size_summary": {
                    "replayable_opportunities": 0,
                    "unique_markets": 0,
                    "resolved_signals": 0,
                },
                "timebound_evidence_window": {
                    "status": "insufficient_data",
                    "source_class": "replayable_opportunities",
                    "start": None,
                    "end": None,
                    "elapsed_hours": None,
                    "observation_count": 0,
                },
                "median_return_pct": 0.0,
                "p05_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "source_evidence": {
                    "wallet_flow_beats_llm_only": None,
                    "combined_sources_beat_single_source_lanes": None,
                    "lane_source_status": "unknown",
                },
            },
            "lmsr": {
                "status": "insufficient_data",
                "confidence_label": "low",
                "deployment_readiness": "insufficient_data",
                "ranking_score": None,
                "sample_size_summary": {
                    "replayable_opportunities": 0,
                    "unique_markets": 0,
                    "resolved_signals": 0,
                },
                "timebound_evidence_window": {
                    "status": "insufficient_data",
                    "source_class": "replayable_opportunities",
                    "start": None,
                    "end": None,
                    "elapsed_hours": None,
                    "observation_count": 0,
                },
                "median_return_pct": 0.0,
                "p05_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "source_evidence": {
                    "wallet_flow_beats_llm_only": None,
                    "combined_sources_beat_single_source_lanes": None,
                    "lane_source_status": "not_audited",
                },
            },
            "cross_platform_arb": {
                "status": "insufficient_data",
                "confidence_label": "low",
                "deployment_readiness": "insufficient_data",
                "ranking_score": None,
                "sample_size_summary": {
                    "replayable_opportunities": 0,
                    "unique_markets": 0,
                    "resolved_signals": 0,
                },
                "timebound_evidence_window": {
                    "status": "insufficient_data",
                    "source_class": "replayable_opportunities",
                    "start": None,
                    "end": None,
                    "elapsed_hours": None,
                    "observation_count": 0,
                },
                "median_return_pct": 0.0,
                "p05_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "source_evidence": {
                    "wallet_flow_beats_llm_only": None,
                    "combined_sources_beat_single_source_lanes": None,
                    "lane_source_status": "not_audited",
                },
            },
            "combined": {
                "status": "ready",
                "confidence_label": "low",
                "deployment_readiness": "research_candidate",
                "ranking_score": 0.03,
                "sample_size_summary": {
                    "replayable_opportunities": 2,
                    "unique_markets": 2,
                    "resolved_signals": 2,
                },
                "timebound_evidence_window": {
                    "status": "ready",
                    "source_class": "replayable_opportunities",
                    "start": "2026-03-08T00:00:00+00:00",
                    "end": "2026-03-08T00:05:00+00:00",
                    "elapsed_hours": 0.083333,
                    "observation_count": 2,
                },
                "median_return_pct": 0.10,
                "p05_return_pct": 0.10,
                "max_drawdown_pct": 0.02,
                "source_evidence": {
                    "wallet_flow_beats_llm_only": None,
                    "combined_sources_beat_single_source_lanes": None,
                    "lane_source_status": "unknown",
                },
            },
        },
        "ranking": [],
        "source_audit": {
            "loaded": False,
            "path": "reports/signal_source_audit.json",
            "capital_ranking_support": None,
            "freshness_hours": None,
            "stale_for_venue_allocation": False,
        },
        "venue_scoreboard": [
            {
                "venue": "polymarket",
                "lane": "btc5",
                "capital_status": "ready_scale",
                "confidence_label": "high",
                "deployment_readiness": "ready_scale",
                "freshness_hours": 0.25,
                "ranking_score": 91.0,
                "settlement_match_rate": None,
                "capital_efficiency_score": 88.0,
                "stage_readiness": {"recommended_stage": 1},
                "sample_size_summary": {
                    "live_filled_rows": 56,
                    "validation_live_filled_rows": 41,
                    "trailing_window_live_fills": 12,
                    "trailing_window_hours": 2.4167,
                },
            }
        ],
        "capital_allocation_recommendation": {
            "next_100_usd": {
                "venue": "polymarket",
                "lane": "btc5",
                "recommended_amount_usd": 100,
                "reasons": ["BTC5 is the top-ranked venue."],
            },
            "next_1000_usd": {
                "recommended_amount_usd": 1000,
                "reasons": ["Deploy the next $1,000 under stage 1."],
                "stage_readiness": {"recommended_stage": 1},
            },
        },
    }

    markdown = render_markdown(report)

    assert "included: llm_only" in markdown
    assert "research_candidate" in markdown
    assert "Venue Capital Scoreboard" in markdown
    assert "Where should the next $100 go?" in markdown
    assert "wallet_flow" in markdown
    assert "zero signals" in markdown


def test_load_wallet_flow_evidence_returns_ready_when_archive_is_sufficient(monkeypatch):
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_edge_config",
        lambda: type("Cfg", (), {"system": type("S", (), {"db_path": "data/edge_discovery.db"})()})(),
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_or_build_wallet_flow_archive",
        lambda db_path, archive_path=None: (
            {
                "schema": "wallet_flow_resolved_signal_archive.v1",
                "counts": {
                    "resolved_qualifying_signals": 4,
                    "unique_markets": 3,
                    "replayable_signals": 4,
                },
                "requirements": {"min_resolved_signals": 3, "min_unique_markets": 2},
                "missing_requirements": [],
                "signals": [
                    {
                        "condition_id": "cond-1",
                        "timestamp_ts": 1700000000,
                        "timestamp": "2026-03-08T00:00:00+00:00",
                        "market_title": "BTC Up or Down 15m",
                        "direction": "buy_yes",
                        "entry_price": 0.52,
                        "win_probability": 0.71,
                        "actual_outcome": "YES_WON",
                        "edge": 0.19,
                        "volume_proxy": 320.0,
                        "liquidity_proxy": 410.0,
                    }
                ],
            },
            "loaded",
        ),
    )

    evidence = load_wallet_flow_evidence()

    assert evidence.status == "ready"
    assert len(evidence.opportunities) == 1
    assert evidence.evidence_summary["archive_source"] == "loaded"
    assert evidence.evidence_summary["resolved_replayable_signals"] == 4
    assert evidence.evidence_summary["unique_markets"] == 3
    assert evidence.opportunities[0].lane == "wallet_flow"


def test_load_wallet_flow_evidence_reports_missing_requirements(monkeypatch):
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_edge_config",
        lambda: type("Cfg", (), {"system": type("S", (), {"db_path": "data/edge_discovery.db"})()})(),
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_or_build_wallet_flow_archive",
        lambda db_path, archive_path=None: (
            {
                "schema": "wallet_flow_resolved_signal_archive.v1",
                "counts": {
                    "resolved_qualifying_signals": 1,
                    "unique_markets": 1,
                    "replayable_signals": 1,
                },
                "requirements": {"min_resolved_signals": 3, "min_unique_markets": 2},
                "missing_requirements": [
                    "resolved_signals 1 < required 3",
                    "unique_markets 1 < required 2",
                ],
                "signals": [],
            },
            "built",
        ),
    )

    evidence = load_wallet_flow_evidence()

    assert evidence.status == "insufficient_data"
    assert any("Resolved qualifying signals: 1 (required >= 3)." in reason for reason in evidence.reasons)
    assert any("Unique resolved markets: 1 (required >= 2)." in reason for reason in evidence.reasons)
    assert any("Missing requirement: resolved_signals 1 < required 3" in reason for reason in evidence.reasons)
    assert evidence.evidence_summary["missing_requirements"]


def test_run_scale_comparison_enriches_with_signal_source_audit(monkeypatch, tmp_path: Path):
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        assumptions=["synthetic llm lane"],
        evidence_summary={"qualified_signals": 10},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-08T00:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": ready_lane,
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    audit_path = tmp_path / "signal_source_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "btc_fast_window_confirmation": {
                    "status": "ready",
                    "summary": {
                        "ready_sources": ["wallet_flow"],
                        "best_source_by_confirmation_lift": "wallet_flow",
                        "confirmation_coverage_ratio": 0.6,
                        "confirmation_resolved_window_coverage": 0.6,
                        "confirmation_executed_window_coverage": 0.4,
                        "confirmation_false_suppression_cost_usd": 0.5,
                        "confirmation_lift_avg_pnl_usd": 1.25,
                        "confirmation_lift_win_rate": 0.15,
                        "confirmation_contradiction_penalty": 0.2,
                    },
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
                "by_source_combo": {
                    "llm": {"win_rate": 0.50},
                    "wallet_flow": {"win_rate": 0.62},
                    "llm+wallet_flow": {"win_rate": 0.70},
                },
                "ranking_snapshot": {
                    "best_component_source": {"source": "wallet_flow", "win_rate": 0.62},
                    "best_source_combo": {"source_combo": "llm+wallet_flow", "win_rate": 0.70},
                },
                "capital_ranking_support": {
                    "stale_threshold_hours": 6.0,
                    "trade_attribution_ready": True,
                    "wallet_flow_vs_llm_status": "ready",
                    "combined_sources_vs_single_source_status": "ready",
                    "best_component_source": "wallet_flow",
                    "best_source_combo": "llm+wallet_flow",
                    "capital_expansion_support_status": "ready",
                    "stage_upgrade_support_status": "ready",
                    "btc_fast_window_confirmation_ready": True,
                    "confirmation_support_status": "ready",
                    "confirmation_sources_ready": ["wallet_flow"],
                    "best_confirmation_source": "wallet_flow",
                    "confirmation_coverage_ratio": 0.6,
                    "confirmation_resolved_window_coverage": 0.6,
                    "confirmation_executed_window_coverage": 0.4,
                    "confirmation_false_suppression_cost_usd": 0.5,
                    "confirmation_lift_avg_pnl_usd": 1.25,
                    "confirmation_lift_win_rate": 0.15,
                    "confirmation_contradiction_penalty": 0.2,
                    "confirmation_blocking_checks": [],
                },
            }
        )
    )

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "out.json",
        markdown_output_path=tmp_path / "out.md",
        signal_source_audit_path=audit_path,
    )

    source_evidence = report["scoreboard"]["llm_only"]["source_evidence"]
    assert source_evidence["signal_source_audit_loaded"] is True
    assert source_evidence["wallet_flow_beats_llm_only"] is True
    assert source_evidence["combined_sources_beat_single_source_lanes"] is True
    assert report["source_audit"]["capital_ranking_support"]["trade_attribution_ready"] is True
    assert report["source_audit"]["btc_fast_window_confirmation"]["status"] == "ready"
    assert source_evidence["lane_source_status"] == "lagging"
    assert report["scoreboard"]["wallet_flow"]["source_evidence"]["lane_source_status"] == "winning"
    assert report["scoreboard"]["combined"]["source_evidence"]["lane_source_status"] == "winning"


def test_run_scale_comparison_uses_confirmation_metrics_in_btc5_ranking(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "backtest.run_scale_comparison._utc_now",
        lambda: datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc),
    )
    ready_lane = LaneEvidence(
        lane="llm_only",
        status="ready",
        evidence_summary={"qualified_signals": 2},
        opportunities=[
            _opportunity("1", "buy_yes", "YES_WON"),
            _opportunity("2", "buy_no", "NO_WON", timestamp="2026-03-10T12:05:00Z"),
        ],
    )
    monkeypatch.setattr(
        "backtest.run_scale_comparison.load_lane_evidences",
        lambda **_: {
            "llm_only": ready_lane,
            "wallet_flow": LaneEvidence(
                lane="wallet_flow",
                status="insufficient_data",
                reasons=["zero qualifying signals"],
                evidence_summary={"resolved_qualifying_signals": 0},
            ),
            "lmsr": LaneEvidence(lane="lmsr", status="insufficient_data", reasons=["missing archive"]),
            "cross_platform_arb": LaneEvidence(
                lane="cross_platform_arb", status="insufficient_data", reasons=["missing archive"]
            ),
        },
    )
    paths = _write_capital_surface_fixtures(
        tmp_path,
        runtime_generated_at="2026-03-10T12:55:00+00:00",
        forecast_generated_at="2026-03-10T12:54:00+00:00",
    )
    monte_carlo_path = _write_capacity_stress_fixture(tmp_path / "btc5_monte_carlo_latest.json")
    wallet_export_path = tmp_path / "Polymarket-History-2026-03-10 (1).csv"
    wallet_export_path.write_text(
        "\n".join(
            [
                '"marketName","action","usdcAmount","tokenAmount","tokenName","timestamp","hash"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Buy","5.0","10.0","Down","1773137400","0x1"',
                '"Bitcoin Up or Down - March 10, 7:30AM-7:35AM ET","Redeem","0","0","","1773137700","0x2"',
            ]
        )
        + "\n"
    )
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    _write_probe_db(probe_db_path, _probe_rows(live_filled=12, failed=2, start_ts=1773147300))

    positive_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "positive.json",
        markdown_output_path=tmp_path / "positive.md",
        signal_source_audit_path=_write_ready_signal_audit(tmp_path / "signal_source_audit_positive.json"),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )
    negative_report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=tmp_path / "negative.json",
        markdown_output_path=tmp_path / "negative.md",
        signal_source_audit_path=_write_negative_confirmation_signal_audit(
            tmp_path / "signal_source_audit_negative.json"
        ),
        btc5_monte_carlo_path=monte_carlo_path,
        wallet_export_path=wallet_export_path,
        btc5_probe_db_path=probe_db_path,
        kalshi_settlements_path=tmp_path / "kalshi_weather_settlements.jsonl",
        kalshi_decisions_path=tmp_path / "kalshi_weather_decisions.jsonl",
        **paths,
    )

    positive_btc5 = next(item for item in positive_report["venue_scoreboard"] if item["venue"] == "polymarket")
    negative_btc5 = next(item for item in negative_report["venue_scoreboard"] if item["venue"] == "polymarket")

    assert positive_btc5["capital_status"] == "ready_scale"
    assert negative_btc5["capital_status"] == "ready_scale"
    assert positive_btc5["confirmation_support"]["status"] == "ready"
    assert negative_btc5["confirmation_support"]["status"] == "ready"
    assert positive_btc5["ranking_score"] > negative_btc5["ranking_score"]
    assert positive_btc5["confirmation_support"]["lift_avg_pnl_usd"] == 1.8
    assert positive_btc5["confirmation_support"]["false_suppression_cost_usd"] == 0.25
    assert negative_btc5["confirmation_support"]["lift_avg_pnl_usd"] == -1.5
    assert negative_btc5["confirmation_support"]["false_suppression_cost_usd"] == 6.0
