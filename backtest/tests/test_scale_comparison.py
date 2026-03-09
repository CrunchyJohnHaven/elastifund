from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.run_scale_comparison import (
    LaneEvidence,
    TradeOpportunity,
    build_combined_evidence,
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
        lambda: {
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

    report = run_scale_comparison(
        bankrolls=[1000.0],
        json_output_path=json_path,
        markdown_output_path=markdown_path,
    )

    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text())
    assert payload["results"]["llm_only"]["1000"]["status"] == "simulated"
    assert payload["results"]["wallet_flow"]["1000"]["status"] == "insufficient_data"
    assert payload["results"]["combined"]["1000"]["status"] == "simulated"
    assert payload["lane_evidence"]["combined"]["evidence_summary"]["included_lanes"] == ["llm_only"]

    markdown = markdown_path.read_text()
    assert "Strategy Scale Comparison" in markdown
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
    }

    markdown = render_markdown(report)

    assert "included: llm_only" in markdown
    assert "wallet_flow" in markdown
    assert "zero signals" in markdown
