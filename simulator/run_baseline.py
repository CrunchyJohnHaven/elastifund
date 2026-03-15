#!/usr/bin/env python3
"""
Run baseline paper-trade simulation and sensitivity analysis.

Usage:
    python -m simulator.run_baseline                    # baseline only
    python -m simulator.run_baseline --sensitivity      # baseline + sensitivity
    python -m simulator.run_baseline --max-markets 50   # limit markets
    python -m simulator.run_baseline --config path.yaml # custom config
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Add parent to path so we can import as package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.api import SimulatorEngine, load_simulator_config, load_simulator_inputs
from simulator.sensitivity import run_sensitivity, format_sensitivity_report

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def format_baseline_report(report: dict) -> str:
    """Format baseline simulation report for terminal output."""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  PAPER-TRADE SIMULATION — BASELINE RUN")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Total signals:     {report['total_trades']}")
    lines.append(f"  Filled trades:     {report['filled_trades']}")
    lines.append(f"  Unfilled trades:   {report['unfilled_trades']}")
    lines.append(f"  Winning trades:    {report['winning_trades']}")
    lines.append(f"  Losing trades:     {report['losing_trades']}")
    lines.append("")
    lines.append(f"  Hit rate:          {report['hit_rate']:.1%}")
    lines.append(f"  Total PnL:         ${report['total_pnl']:+.2f}")
    lines.append(f"  Avg PnL/trade:     ${report['avg_pnl_per_trade']:+.4f}")
    lines.append(f"  Final capital:     ${report['final_capital']:.2f}")
    lines.append(f"  Return:            {report['return_pct']:.1%}")
    lines.append("")
    lines.append(f"  Max drawdown:      ${report['max_drawdown']:.2f}")
    lines.append(f"  Max drawdown %:    {report['max_drawdown_pct']:.1%}")
    lines.append("")
    lines.append(f"  Avg edge (pre):    {report['avg_edge_pre_cost']:.1%}")
    lines.append(f"  Avg edge (post):   {report['avg_edge_post_cost']:.1%}")
    lines.append("")
    lines.append(f"  Total turnover:    ${report['total_turnover']:.2f}")
    lines.append(f"  Total fees:        ${report['total_fees']:.2f}")
    lines.append(f"  Fee drag:          {report['fee_drag_pct']:.2%}")
    lines.append(f"  Slippage drag:     {report['slippage_drag_pct']:.2%}")
    lines.append(f"  Spread drag:       {report['spread_drag_pct']:.2%}")

    # Direction breakdown
    if report.get("by_direction"):
        lines.append("")
        lines.append("  By Direction:")
        for direction, stats in report["by_direction"].items():
            if stats["count"] > 0:
                lines.append(
                    f"    {direction:8s}: {stats['count']:4d} trades, "
                    f"{stats['win_rate']:.1%} win, "
                    f"${stats['total_pnl']:+.2f} total"
                )

    # Daily summaries (first 10)
    if report.get("per_day_summary"):
        lines.append("")
        lines.append("  Daily Summary (first 10 days):")
        lines.append(f"  {'Date':>12s} {'Trades':>7s} {'Net PnL':>10s} {'Cum PnL':>10s} {'Capital':>10s} {'DD%':>7s}")
        for day in report["per_day_summary"][:10]:
            lines.append(
                f"  {day['date']:>12s} {day['trades_resolved']:>7d} "
                f"${day['net_pnl']:>8.2f} ${day['cumulative_pnl']:>8.2f} "
                f"${day['capital_eod']:>8.2f} {day['drawdown']:>6.1%}"
            )

    # Sample trades (first 10)
    if report.get("per_trade_log"):
        lines.append("")
        lines.append("  Sample Trades (first 10 filled):")
        filled = [t for t in report["per_trade_log"] if t["fill_price"] > 0][:10]
        for t in filled:
            status = "WIN " if t["won"] else "LOSS"
            lines.append(
                f"    [{status}] {t['direction']:8s} @ {t['entry_price']:.2f} "
                f"(fill: {t['fill_price']:.4f}) "
                f"${t['pnl']:+.4f} slip={t['slippage']:.4f}"
            )
            lines.append(f"           {t['question']}")

    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Paper-trade simulator baseline run")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--max-markets", type=int, default=0, help="Limit markets (0=all)")
    parser.add_argument("--sensitivity", action="store_true", help="Run sensitivity analysis")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    # Load
    config = load_simulator_config(args.config)
    markets, cache = load_simulator_inputs()

    # Baseline run
    print("\nRunning baseline simulation...")
    t0 = time.time()
    engine = SimulatorEngine(config)
    report = engine.run(markets, cache, max_markets=args.max_markets)
    elapsed = time.time() - t0

    print(format_baseline_report(report))
    print(f"\n  Completed in {elapsed:.1f}s")

    # Save baseline
    baseline_path = os.path.join(args.output, "baseline_results.json")
    with open(baseline_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Saved to {baseline_path}")

    # Sensitivity
    if args.sensitivity:
        print("\nRunning sensitivity analysis...")
        t0 = time.time()
        sens = run_sensitivity(config, markets, cache, max_markets=args.max_markets)
        elapsed = time.time() - t0

        print(format_sensitivity_report(sens))
        print(f"\n  Sensitivity completed in {elapsed:.1f}s")

        sens_path = os.path.join(args.output, "sensitivity_results.json")
        with open(sens_path, "w") as f:
            json.dump(sens, f, indent=2, default=str)
        print(f"  Saved to {sens_path}")

    # Reproducibility check: run again, verify identical output
    print("\nReproducibility check...")
    engine2 = SimulatorEngine(config)
    report2 = engine2.run(markets, cache, max_markets=args.max_markets)
    if report["total_pnl"] == report2["total_pnl"] and report["filled_trades"] == report2["filled_trades"]:
        print("  PASS: identical results on re-run")
    else:
        print(f"  FAIL: PnL differs: ${report['total_pnl']:.4f} vs ${report2['total_pnl']:.4f}")


if __name__ == "__main__":
    main()
