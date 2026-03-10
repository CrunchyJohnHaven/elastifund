from __future__ import annotations

import json
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

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=json_path,
        markdown_output_path=markdown_path,
        signal_source_audit_path=tmp_path / "missing_signal_source_audit.json",
        runtime_truth_path=runtime_truth_path,
        public_runtime_snapshot_path=public_runtime_snapshot_path,
        btc5_autoresearch_path=btc5_autoresearch_path,
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
    assert payload["source_audit"]["loaded"] is False
    assert payload["ranking"]
    assert payload["ranking"][0]["lane"] in {"combined", "llm_only"}
    assert payload["venue_scoreboard"][0]["venue"] == "polymarket"
    assert payload["venue_scoreboard"][0]["lane"] == "btc5"
    assert payload["venue_scoreboard"][0]["capital_status"] == "ready_test_tranche"
    assert payload["venue_scoreboard"][1]["venue"] == "kalshi"
    assert payload["venue_scoreboard"][1]["capital_status"] == "hold"
    assert payload["venue_scoreboard"][1]["settlement_match_rate"] == 0.0
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["venue"] == "polymarket"
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["lane"] == "btc5"
    assert payload["capital_allocation_recommendation"]["next_100_usd"]["recommended_amount_usd"] == 100
    assert payload["capital_allocation_recommendation"]["next_1000_usd"]["status"] == "hold"
    assert payload["capital_allocation_recommendation"]["next_1000_usd"]["recommended_amount_usd"] == 0

    markdown = markdown_path.read_text()
    assert "Strategy Scale Comparison" in markdown
    assert "Lane Scoreboard" in markdown
    assert "Venue Capital Scoreboard" in markdown
    assert "Where should the next $100 go?" in markdown
    assert "Where should the next $1,000 go?" in markdown
    assert "wallet_flow" in markdown
    assert "insufficient_data" in markdown


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
                "capital_status": "ready_test_tranche",
                "confidence_label": "high",
                "deployment_readiness": "ready_test_tranche",
                "freshness_hours": 0.25,
                "ranking_score": 91.0,
                "settlement_match_rate": None,
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
                "recommended_amount_usd": 0,
                "reasons": ["Fund capital truth is still blocked."],
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
    assert source_evidence["lane_source_status"] == "lagging"
    assert report["scoreboard"]["wallet_flow"]["source_evidence"]["lane_source_status"] == "winning"
    assert report["scoreboard"]["combined"]["source_evidence"]["lane_source_status"] == "winning"
