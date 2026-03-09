#!/usr/bin/env python3
"""Bankroll scale comparison for currently evidenced strategy lanes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.run_combined import _build_calibrator, load_data as load_llm_backtest_data
from simulator.fill_model import simulate_fill
from simulator.metrics import compute_max_drawdown
from simulator.simulator import SimulatorEngine, load_config as load_simulator_config
from simulator.sizing import capped_size
from src.config import load_config as load_edge_config
from src.feature_engineering import FeatureEngineer
from src.strategies.wallet_flow import WalletFlowMomentumStrategy


LOGGER = logging.getLogger(__name__)

DEFAULT_BANKROLLS = [1000.0, 10000.0, 100000.0]
DEFAULT_MARKDOWN_PATH = ROOT / "reports" / "strategy_scale_comparison.md"
DEFAULT_JSON_PATH = ROOT / "reports" / "strategy_scale_comparison.json"

LLM_KELLY_FRACTION = 0.25
FAST_KELLY_FRACTION = 1.0 / 16.0
MAX_ALLOCATION = 0.20
MAX_POSITION_USD = 5.0
MIN_POSITION_USD = 1.0
LLM_ENTRY_PRICE = 0.50
LLM_YES_THRESHOLD = 0.15
LLM_NO_THRESHOLD = 0.05


@dataclass(frozen=True)
class TradeOpportunity:
    """Single replayable trade opportunity for a strategy lane."""

    lane: str
    signal_id: str
    timestamp: str
    question: str
    direction: str
    market_price: float
    win_probability: float
    actual_outcome: str
    edge: float
    volume: float
    liquidity: float
    kelly_fraction: float


@dataclass
class LaneEvidence:
    """Evidence status for one lane."""

    lane: str
    status: str
    reasons: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    opportunities: list[TradeOpportunity] = field(default_factory=list)


def build_conservative_simulation_config(bankroll: float) -> dict[str, Any]:
    """Reuse simulator cost assumptions while restoring conservative bankroll limits."""

    config = copy.deepcopy(load_simulator_config())
    config["capital"]["initial"] = float(bankroll)
    config["sizing"]["method"] = "capped_kelly"
    config["sizing"]["kelly"]["kelly_fraction"] = LLM_KELLY_FRACTION
    config["sizing"]["kelly"]["max_allocation"] = MAX_ALLOCATION
    config["sizing"]["kelly"]["min_size"] = MIN_POSITION_USD
    config["sizing"]["capped"]["max_position_usd"] = MAX_POSITION_USD
    config["sizing"]["capped"]["min_position_usd"] = MIN_POSITION_USD
    config["execution"]["mode"] = "taker"
    config["execution"]["max_concurrent_positions"] = 1
    config["execution"]["min_edge_threshold"] = LLM_NO_THRESHOLD
    config["filters"]["min_liquidity"] = 0
    config["filters"]["min_volume"] = 0
    config["filters"]["price_range"] = [0.10, 0.90]
    return config


def load_llm_only_evidence() -> LaneEvidence:
    """Convert the existing LLM backtest surface into replayable opportunities."""

    markets, cache, hashes = load_llm_backtest_data()
    calibrator = _build_calibrator()

    opportunities: list[TradeOpportunity] = []
    cached_estimates = 0
    qualified_signals = 0

    for market in sorted(markets, key=lambda row: (row.get("end_date") or "", row.get("id") or "")):
        question = str(market["question"])
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        estimate = cache.get(key)
        if estimate is None:
            continue

        cached_estimates += 1
        raw_probability = float(estimate["probability"])
        calibrated_probability = float(calibrator.correct(raw_probability))
        edge = calibrated_probability - LLM_ENTRY_PRICE
        direction = "buy_yes" if edge > 0 else "buy_no"
        abs_edge = abs(edge)
        threshold = LLM_YES_THRESHOLD if direction == "buy_yes" else LLM_NO_THRESHOLD

        if abs_edge < threshold:
            continue

        qualified_signals += 1
        win_probability = calibrated_probability if direction == "buy_yes" else 1.0 - calibrated_probability
        opportunities.append(
            TradeOpportunity(
                lane="llm_only",
                signal_id=str(market.get("id") or qualified_signals),
                timestamp=str(market.get("end_date") or ""),
                question=question,
                direction=direction,
                market_price=LLM_ENTRY_PRICE,
                win_probability=win_probability,
                actual_outcome=str(market["actual_outcome"]),
                edge=abs_edge,
                volume=float(market.get("volume") or 0.0),
                liquidity=float(market.get("liquidity") or 0.0),
                kelly_fraction=LLM_KELLY_FRACTION,
            )
        )

    if not opportunities:
        return LaneEvidence(
            lane="llm_only",
            status="insufficient_data",
            reasons=["No qualified LLM signals were available after calibration and asymmetric thresholding."],
            assumptions=[
                "Fixed 0.50 entry-price baseline from backtest/kelly_comparison.py because historical entry snapshots are not stored.",
                "Quarter-Kelly sizing with a hard $5 position cap and 20% max allocation.",
                "Simulator taker fill model for deterministic fee/slippage replay.",
            ],
            evidence_summary={
                "historical_markets": len(markets),
                "cached_estimates": cached_estimates,
                "qualified_signals": qualified_signals,
                "data_hashes": hashes,
            },
        )

    return LaneEvidence(
        lane="llm_only",
        status="ready",
        reasons=[],
        assumptions=[
            "Fixed 0.50 entry-price baseline from backtest/kelly_comparison.py because historical entry snapshots are not stored.",
            "Calibrated Claude probabilities via backtest/run_combined.py with live-style asymmetric thresholds (YES 15%, NO 5%).",
            "Quarter-Kelly sizing with a hard $5 position cap and 20% max allocation.",
            "Simulator taker fill model for deterministic fee/slippage replay.",
        ],
        evidence_summary={
            "historical_markets": len(markets),
            "cached_estimates": cached_estimates,
            "qualified_signals": qualified_signals,
            "data_hashes": hashes,
        },
        opportunities=opportunities,
    )


def load_wallet_flow_evidence() -> LaneEvidence:
    """Check whether wallet-flow currently has replayable evidence."""

    config = load_edge_config()
    bundle = FeatureEngineer(config.system.db_path).build_feature_bundle()
    strategy = WalletFlowMomentumStrategy()
    signals = strategy.generate_signals(bundle.markets, bundle.btc_prices, bundle.trades, bundle.features)
    resolved_signals = [signal for signal in signals if signal.condition_id in bundle.resolutions]

    return LaneEvidence(
        lane="wallet_flow",
        status="insufficient_data",
        reasons=[
            (
                "Current WalletFlowMomentumStrategy produced "
                f"{len(resolved_signals)} resolved qualifying signals from data/edge_discovery.db."
            ),
            "Without resolved qualifying signals, bankroll replay would fabricate wallet-flow P&L.",
        ],
        assumptions=[
            "Evidence check uses src/strategies/wallet_flow.py with the repo's current edge-discovery SQLite data.",
            "Fast-lane sizing target remains 1/16 Kelly once there is a resolved signal archive to replay.",
        ],
        evidence_summary={
            "db_path": config.system.db_path,
            "markets": len(bundle.markets),
            "features": len(bundle.features),
            "trades": len(bundle.trades),
            "resolved_markets": len(bundle.resolutions),
            "qualifying_signals": len(signals),
            "resolved_qualifying_signals": len(resolved_signals),
        },
    )


def load_lmsr_evidence() -> LaneEvidence:
    """Surface the current repo truth for LMSR replay readiness."""

    return LaneEvidence(
        lane="lmsr",
        status="insufficient_data",
        reasons=[
            "bot/lmsr_engine.py is implemented, but the repo does not contain a resolved historical LMSR signal archive for bankroll replay.",
            "No existing backtest/simulator adapter in this repo maps historical resolutions to LMSR engine decisions without inventing fills.",
        ],
        assumptions=[
            "Fast-lane sizing target would be 1/16 Kelly under the current operating rules once resolved signals exist.",
        ],
        evidence_summary={
            "engine_file": "bot/lmsr_engine.py",
            "resolved_signal_archive_present": False,
            "replay_adapter_present": False,
        },
    )


def load_cross_platform_arb_evidence() -> LaneEvidence:
    """Surface the current repo truth for cross-platform arb replay readiness."""

    return LaneEvidence(
        lane="cross_platform_arb",
        status="insufficient_data",
        reasons=[
            "bot/cross_platform_arb.py is unit-tested, but the repo does not contain a matched historical Polymarket/Kalshi execution archive with closed arbitrage outcomes.",
            "Assigning replay P&L without matched historical fills would be fabricated.",
        ],
        assumptions=[
            "High-confidence lane sizing remains quarter-Kelly with the same $5 hard cap once matched fills are archived.",
        ],
        evidence_summary={
            "scanner_file": "bot/cross_platform_arb.py",
            "matched_fill_archive_present": False,
            "closed_trade_archive_present": False,
        },
    )


def load_lane_evidences() -> dict[str, LaneEvidence]:
    """Collect the current replay readiness state for every requested lane."""

    return {
        "llm_only": load_llm_only_evidence(),
        "wallet_flow": load_wallet_flow_evidence(),
        "lmsr": load_lmsr_evidence(),
        "cross_platform_arb": load_cross_platform_arb_evidence(),
    }


def simulate_lane(opportunities: list[TradeOpportunity], bankroll: float) -> dict[str, Any]:
    """Replay one lane using simulator fill logic and conservative bankroll caps."""

    if not opportunities:
        return {
            "status": "insufficient_data",
            "reasons": ["No replayable opportunities were available."],
        }

    config = build_conservative_simulation_config(bankroll)
    engine = SimulatorEngine(config)

    capital = float(bankroll)
    equity_curve = [capital]
    trade_count = 0
    attempts = 0
    wins = 0
    total_turnover = 0.0
    total_fees = 0.0
    total_slippage_cost = 0.0
    total_spread_cost = 0.0
    utilization_samples: list[float] = []

    for opportunity in sorted(opportunities, key=lambda item: (item.timestamp, item.signal_id)):
        size = capped_size(
            capital=capital,
            edge=opportunity.edge,
            win_probability=opportunity.win_probability,
            kelly_fraction=opportunity.kelly_fraction,
            max_allocation=MAX_ALLOCATION,
            max_position_usd=MAX_POSITION_USD,
            min_position_usd=MIN_POSITION_USD,
        )
        if size <= 0.0:
            continue

        attempts += 1
        capital_before = capital
        fill = simulate_fill(
            market_price=opportunity.market_price,
            direction=opportunity.direction,
            edge=opportunity.edge,
            order_size_usd=size,
            volume=opportunity.volume,
            liquidity=max(opportunity.liquidity, 1.0),
            config=config,
            rng=engine.rng,
        )
        if not fill.filled:
            continue

        won, pnl, winner_fee = engine._resolve(
            direction=opportunity.direction,
            fill_price=fill.fill_price,
            size=size,
            actual=opportunity.actual_outcome,
            entry_fee=fill.fee,
        )
        capital += pnl
        equity_curve.append(capital)

        trade_count += 1
        wins += int(won)
        total_turnover += size
        total_fees += fill.fee + winner_fee
        total_slippage_cost += fill.slippage * size
        total_spread_cost += fill.spread_cost * size
        utilization_samples.append(size / capital_before if capital_before > 0 else 0.0)

    max_drawdown_usd, max_drawdown_pct = compute_max_drawdown(equity_curve)
    return {
        "status": "simulated",
        "attempted_trades": attempts,
        "trade_count": trade_count,
        "wins": wins,
        "win_rate": round((wins / trade_count) if trade_count else 0.0, 6),
        "starting_bankroll_usd": round(float(bankroll), 2),
        "final_capital_usd": round(capital, 2),
        "return_pct": round(((capital - bankroll) / bankroll) if bankroll else 0.0, 6),
        "max_drawdown_usd": round(max_drawdown_usd, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "capital_utilization_pct": round(statistics.mean(utilization_samples) if utilization_samples else 0.0, 6),
        "fee_drag_pct": round((total_fees / total_turnover) if total_turnover else 0.0, 6),
        "total_turnover_usd": round(total_turnover, 2),
        "total_fees_usd": round(total_fees, 2),
        "total_slippage_cost_usd": round(total_slippage_cost, 2),
        "total_spread_cost_usd": round(total_spread_cost, 2),
    }


def build_insufficient_results(evidence: LaneEvidence, bankrolls: list[float]) -> dict[str, Any]:
    """Expand one insufficient-data lane across all bankrolls."""

    return {
        str(int(bankroll)): {
            "status": "insufficient_data",
            "reasons": evidence.reasons,
            "evidence_summary": evidence.evidence_summary,
        }
        for bankroll in bankrolls
    }


def build_combined_evidence(lane_evidences: dict[str, LaneEvidence]) -> LaneEvidence:
    """Build the combined executable lane from all ready evidence."""

    supported = [lane for lane, evidence in lane_evidences.items() if evidence.status == "ready" and evidence.opportunities]
    unsupported = [lane for lane, evidence in lane_evidences.items() if evidence.status != "ready" or not evidence.opportunities]

    if not supported:
        return LaneEvidence(
            lane="combined",
            status="insufficient_data",
            reasons=["No lane has enough evidence for replay, so combined cannot produce defensible P&L."],
            assumptions=["Combined only includes lanes with replayable evidence."],
            evidence_summary={
                "included_lanes": [],
                "excluded_lanes": unsupported,
            },
        )

    combined_opportunities: list[TradeOpportunity] = []
    combined_assumptions: list[str] = ["Combined only includes lanes with replayable evidence."]
    for lane in supported:
        combined_opportunities.extend(lane_evidences[lane].opportunities)
        combined_assumptions.extend(lane_evidences[lane].assumptions)

    combined_assumptions.append(
        "Unsupported lanes remain excluded until they produce resolved replayable evidence; no synthetic P&L is assigned."
    )
    return LaneEvidence(
        lane="combined",
        status="ready",
        reasons=[],
        assumptions=_dedupe_preserve_order(combined_assumptions),
        evidence_summary={
            "included_lanes": supported,
            "excluded_lanes": unsupported,
            "combined_opportunities": len(combined_opportunities),
        },
        opportunities=combined_opportunities,
    )


def build_report(bankrolls: list[float]) -> dict[str, Any]:
    """Build the full scale-comparison payload."""

    lane_evidences = load_lane_evidences()
    combined_evidence = build_combined_evidence(lane_evidences)
    all_evidences = {
        **lane_evidences,
        "combined": combined_evidence,
    }

    results: dict[str, dict[str, Any]] = {}
    for lane, evidence in all_evidences.items():
        if evidence.status != "ready" or not evidence.opportunities:
            results[lane] = build_insufficient_results(evidence, bankrolls)
            continue

        lane_results: dict[str, Any] = {}
        for bankroll in bankrolls:
            lane_results[str(int(bankroll))] = simulate_lane(evidence.opportunities, bankroll)
        results[lane] = lane_results

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "as_of_date": "2026-03-08",
        "bankrolls": [int(bankroll) for bankroll in bankrolls],
        "risk_caps": {
            "max_position_usd": MAX_POSITION_USD,
            "max_allocation_pct": MAX_ALLOCATION,
            "llm_kelly_fraction": LLM_KELLY_FRACTION,
            "fast_kelly_fraction": FAST_KELLY_FRACTION,
            "min_position_usd": MIN_POSITION_USD,
        },
        "execution_assumptions": {
            "simulator_mode": "taker",
            "winner_fee_rate": load_simulator_config()["fees"]["winner_fee"],
            "entry_price_baseline_llm": LLM_ENTRY_PRICE,
            "yes_threshold_llm": LLM_YES_THRESHOLD,
            "no_threshold_llm": LLM_NO_THRESHOLD,
        },
        "lane_evidence": {
            lane: {
                "status": evidence.status,
                "reasons": evidence.reasons,
                "assumptions": evidence.assumptions,
                "evidence_summary": evidence.evidence_summary,
            }
            for lane, evidence in all_evidences.items()
        },
        "results": results,
    }


def write_report(report: dict[str, Any], json_output_path: Path, markdown_output_path: Path) -> None:
    """Write the JSON and Markdown artifacts."""

    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.parent.mkdir(parents=True, exist_ok=True)

    json_output_path.write_text(json.dumps(report, indent=2))
    markdown_output_path.write_text(render_markdown(report))


def render_markdown(report: dict[str, Any]) -> str:
    """Render the scale-comparison payload as Markdown."""

    lines: list[str] = []
    lines.append("# Strategy Scale Comparison")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- Repo truth date: {report['as_of_date']}")
    lines.append(
        "- Conservative caps: "
        f"${report['risk_caps']['max_position_usd']:.0f} max position, "
        f"{report['risk_caps']['llm_kelly_fraction']:.2f} LLM Kelly fraction, "
        f"{report['risk_caps']['fast_kelly_fraction']:.4f} fast-lane Kelly fraction, "
        f"{report['risk_caps']['max_allocation_pct']:.0%} max allocation."
    )
    lines.append(
        "- Execution replay: "
        f"{report['execution_assumptions']['simulator_mode']} fills from `simulator/`, "
        f"LLM entry baseline {report['execution_assumptions']['entry_price_baseline_llm']:.2f}."
    )
    lines.append("")

    lines.append("## Current Readiness")
    for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
        evidence = report["lane_evidence"][lane]
        status = evidence["status"]
        if status == "ready":
            summary = evidence["evidence_summary"]
            if lane == "combined":
                lines.append(
                    f"- `{lane}`: ready; includes {', '.join(summary.get('included_lanes', [])) or 'no lanes'}."
                )
            else:
                lines.append(f"- `{lane}`: ready.")
        else:
            lines.append(f"- `{lane}`: `insufficient_data`.")
            for reason in evidence["reasons"]:
                lines.append(f"  - {reason}")
    lines.append("")

    for bankroll in report["bankrolls"]:
        lines.append(f"## Starting Bankroll ${bankroll:,.0f}")
        lines.append("")
        lines.append("| Lane | Status | Return | Max Drawdown | Trades | Capital Utilization | Fee Drag | Notes |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")

        for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
            result = report["results"][lane][str(bankroll)]
            if result["status"] == "simulated":
                note = ""
                if lane == "combined":
                    combined_meta = report["lane_evidence"]["combined"]["evidence_summary"]
                    note = "included: " + ", ".join(combined_meta.get("included_lanes", []))
                lines.append(
                    "| "
                    f"{lane} | simulated | {result['return_pct']:.2%} | {result['max_drawdown_pct']:.2%} "
                    f"(${result['max_drawdown_usd']:.2f}) | {result['trade_count']} | "
                    f"{result['capital_utilization_pct']:.2%} | {result['fee_drag_pct']:.2%} | {note} |"
                )
            else:
                reason = "; ".join(result.get("reasons", []))
                lines.append(
                    f"| {lane} | insufficient_data | — | — | — | — | — | {reason} |"
                )
        lines.append("")

    lines.append("## Assumptions")
    assumptions = _dedupe_preserve_order(
        assumption
        for evidence in report["lane_evidence"].values()
        for assumption in evidence.get("assumptions", [])
    )
    for assumption in assumptions:
        lines.append(f"- {assumption}")
    lines.append("")

    lines.append("## Evidence Summary")
    for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
        lines.append(f"### {lane}")
        summary = report["lane_evidence"][lane]["evidence_summary"]
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_scale_comparison(
    bankrolls: list[float] | None = None,
    json_output_path: Path = DEFAULT_JSON_PATH,
    markdown_output_path: Path = DEFAULT_MARKDOWN_PATH,
) -> dict[str, Any]:
    """Public entry point for tests and the CLI."""

    bankrolls = bankrolls or DEFAULT_BANKROLLS
    report = build_report([float(bankroll) for bankroll in bankrolls])
    write_report(report, json_output_path=json_output_path, markdown_output_path=markdown_output_path)
    return report


def _dedupe_preserve_order(values: Any) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare strategy scale outcomes at multiple bankrolls.")
    parser.add_argument(
        "--bankrolls",
        nargs="+",
        type=float,
        default=DEFAULT_BANKROLLS,
        help="Starting bankrolls in USD (default: 1000 10000 100000)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"JSON output path (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_PATH,
        help=f"Markdown output path (default: {DEFAULT_MARKDOWN_PATH})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    report = run_scale_comparison(
        bankrolls=args.bankrolls,
        json_output_path=args.json_output,
        markdown_output_path=args.markdown_output,
    )
    combined = report["lane_evidence"]["combined"]["evidence_summary"]
    included = ", ".join(combined.get("included_lanes", [])) or "none"
    print(f"Wrote {args.json_output}")
    print(f"Wrote {args.markdown_output}")
    print(f"Combined executable lanes: {included}")


if __name__ == "__main__":
    main()
