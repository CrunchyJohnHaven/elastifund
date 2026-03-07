#!/usr/bin/env python3
"""
CLI entry point for the paper-trade simulator.

Usage:
    python run_sim.py run                          # Run with default config
    python run_sim.py run --config custom.yaml     # Run with custom config
    python run_sim.py run --mode maker             # Override execution mode
    python run_sim.py run --sizing kelly           # Override sizing method
    python run_sim.py audit                        # Run and produce audit summary
    python run_sim.py compare                      # Compare taker vs maker
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from engine import PaperTradeSimulator
from metrics import SimulationReport


DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"
DEFAULT_MARKETS = Path(__file__).parent.parent / "backtest" / "data" / "historical_markets.json"
DEFAULT_CACHE = Path(__file__).parent.parent / "backtest" / "data" / "claude_cache.json"
OUTPUT_DIR = Path(__file__).parent / "output"


def run_simulation(args) -> SimulationReport:
    """Run a single simulation with the specified config."""
    config_path = Path(args.config)

    # Apply CLI overrides to config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    if args.mode:
        config["execution"]["mode"] = args.mode
    if args.sizing:
        config["sizing"]["method"] = args.sizing
    if args.capital:
        config["capital"]["initial"] = args.capital
    if args.seed is not None:
        config["random_seed"] = args.seed

    # Write modified config to temp file if overrides applied
    if any([args.mode, args.sizing, args.capital, args.seed is not None]):
        tmp_config = OUTPUT_DIR / "_tmp_config.yaml"
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(tmp_config, "w") as f:
            yaml.dump(config, f)
        config_path = tmp_config

    sim = PaperTradeSimulator(config_path)
    report = sim.run(
        markets_path=args.markets,
        cache_path=args.cache,
    )

    return report


def print_summary(report: SimulationReport):
    """Print a formatted summary to stdout."""
    print("\n" + "=" * 70)
    print("PAPER-TRADE SIMULATION RESULTS")
    print("=" * 70)

    print(f"\n{'Metric':<35} {'Value':>15}")
    print("-" * 50)
    print(f"{'Total signals':<35} {report.total_trades:>15,}")
    print(f"{'Filled trades':<35} {report.filled_trades:>15,}")
    print(f"{'Unfilled trades':<35} {report.unfilled_trades:>15,}")
    print(f"{'Winning trades':<35} {report.winning_trades:>15,}")
    print(f"{'Losing trades':<35} {report.losing_trades:>15,}")
    print(f"{'Hit rate':<35} {report.hit_rate:>14.1%}")
    print()
    print(f"{'Total PnL':<35} {'$' + f'{report.total_pnl:,.2f}':>15}")
    print(f"{'Avg PnL / trade':<35} {'$' + f'{report.avg_pnl_per_trade:,.4f}':>15}")
    print(f"{'Final capital':<35} {'$' + f'{report.final_capital:,.2f}':>15}")
    print(f"{'Return':<35} {report.return_pct:>14.1%}")
    print()
    print(f"{'Max drawdown ($)':<35} {'$' + f'{report.max_drawdown:,.2f}':>15}")
    print(f"{'Max drawdown (%)':<35} {report.max_drawdown_pct:>14.1%}")
    print()
    print(f"{'Avg edge (pre-cost)':<35} {report.avg_edge_pre_cost:>14.4f}")
    print(f"{'Avg edge (post-cost)':<35} {report.avg_edge_post_cost:>14.4f}")
    print()
    print(f"{'Total turnover':<35} {'$' + f'{report.total_turnover:,.2f}':>15}")
    print(f"{'Total fees':<35} {'$' + f'{report.total_fees:,.2f}':>15}")
    print(f"{'Fee drag (% of turnover)':<35} {report.fee_drag_pct:>14.4%}")
    print(f"{'Slippage drag':<35} {report.slippage_drag_pct:>14.4%}")
    print(f"{'Spread drag':<35} {report.spread_drag_pct:>14.4%}")

    print("\n--- By Direction ---")
    for direction, stats in report.by_direction.items():
        print(f"  {direction}: {stats['count']} trades, "
              f"{stats['win_rate']:.1%} win rate, "
              f"avg PnL ${stats['avg_pnl']:.4f}, "
              f"total PnL ${stats['total_pnl']:.2f}")

    if report.assumptions_impact:
        print("\n--- Assumption Impact (Audit) ---")
        ai = report.assumptions_impact
        print(f"  Gross PnL (before costs):  ${ai['gross_pnl_before_costs']:,.2f}")
        print(f"  Net PnL (after costs):     ${ai['net_pnl_after_costs']:,.2f}")
        print(f"  Total cost drag:           ${ai['total_cost_drag']:,.2f}")
        print(f"  Fees:       ${ai['fee_impact']['total_usd']:>8,.2f}  "
              f"({ai['fee_impact']['pct_of_gross']:.1f}% of gross PnL)")
        print(f"  Slippage:   ${ai['slippage_impact']['total_usd']:>8,.2f}  "
              f"({ai['slippage_impact']['pct_of_gross']:.1f}% of gross PnL)")
        print(f"  Spread:     ${ai['spread_impact']['total_usd']:>8,.2f}  "
              f"({ai['spread_impact']['pct_of_gross']:.1f}% of gross PnL)")
        print(f"  Fill rate:  {ai['fill_rate_pct']:.1f}%")
        print(f"  DOMINANT:   {ai['dominant_assumption']}")

    print()


def save_report(report: SimulationReport, label: str = "baseline"):
    """Save full report to JSON."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"sim_{label}_{ts}.json"

    data = {
        "run_at": datetime.utcnow().isoformat() + "Z",
        "label": label,
        "summary": {
            "total_trades": report.total_trades,
            "filled_trades": report.filled_trades,
            "unfilled_trades": report.unfilled_trades,
            "winning_trades": report.winning_trades,
            "losing_trades": report.losing_trades,
            "hit_rate": round(report.hit_rate, 4),
            "total_pnl": round(report.total_pnl, 4),
            "avg_pnl_per_trade": round(report.avg_pnl_per_trade, 4),
            "max_drawdown": round(report.max_drawdown, 4),
            "max_drawdown_pct": round(report.max_drawdown_pct, 4),
            "avg_edge_pre_cost": round(report.avg_edge_pre_cost, 4),
            "avg_edge_post_cost": round(report.avg_edge_post_cost, 4),
            "total_turnover": round(report.total_turnover, 2),
            "total_fees": round(report.total_fees, 4),
            "fee_drag_pct": round(report.fee_drag_pct, 6),
            "slippage_drag_pct": round(report.slippage_drag_pct, 6),
            "spread_drag_pct": round(report.spread_drag_pct, 6),
            "final_capital": round(report.final_capital, 2),
            "return_pct": round(report.return_pct, 4),
        },
        "by_direction": report.by_direction,
        "assumptions_impact": report.assumptions_impact,
        "per_day_summary": report.per_day_summary,
        "per_trade_log": report.per_trade_log,
    }

    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Report saved to {out_path}")
    return out_path


def cmd_run(args):
    """Run a single simulation."""
    report = run_simulation(args)
    print_summary(report)
    save_report(report, label=args.label or "baseline")


def cmd_audit(args):
    """Run baseline scenario and produce audit summary."""
    args.label = "audit"
    report = run_simulation(args)
    print_summary(report)
    path = save_report(report, label="audit")

    # Print audit conclusion
    ai = report.assumptions_impact
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY: Which Assumptions Dominate Results")
    print("=" * 70)
    print(f"""
1. DOMINANT COST: {ai.get('dominant_assumption', 'N/A')}
   - Total cost drag: ${ai.get('total_cost_drag', 0):,.2f} on ${report.total_turnover:,.2f} turnover

2. FEES ({ai['fee_impact']['pct_of_gross']:.1f}% of gross PnL):
   - Entry fees: ${ai['fee_impact']['total_usd']:,.2f}
   - At {report.fee_drag_pct:.4%} of turnover
   - Verdict: {'MATERIAL' if ai['fee_impact']['pct_of_gross'] > 10 else 'MANAGEABLE'}

3. SLIPPAGE ({ai['slippage_impact']['pct_of_gross']:.1f}% of gross PnL):
   - Slippage cost: ${ai['slippage_impact']['total_usd']:,.2f}
   - At {report.slippage_drag_pct:.4%} of turnover
   - Verdict: {'MATERIAL' if ai['slippage_impact']['pct_of_gross'] > 10 else 'MANAGEABLE'}

4. SPREAD ({ai['spread_impact']['pct_of_gross']:.1f}% of gross PnL):
   - Spread cost: ${ai['spread_impact']['total_usd']:,.2f}
   - At {report.spread_drag_pct:.4%} of turnover
   - Verdict: {'MATERIAL' if ai['spread_impact']['pct_of_gross'] > 10 else 'MANAGEABLE'}

5. FILL RATE: {ai.get('fill_rate_pct', 100):.1f}%
   - Unfilled: {ai.get('unfilled_trades', 0)} signals
   - Verdict: {'LOW — consider taker mode' if ai.get('fill_rate_pct', 100) < 50 else 'ACCEPTABLE'}

6. OVERALL:
   - Gross PnL: ${ai.get('gross_pnl_before_costs', 0):,.2f}
   - Net PnL:   ${ai.get('net_pnl_after_costs', 0):,.2f}
   - Cost drag eats {(1 - ai.get('net_pnl_after_costs', 0) / ai.get('gross_pnl_before_costs', 1)) * 100:.1f}% of gross profit
""")


def cmd_compare(args):
    """Compare taker vs maker execution modes."""
    results = {}
    for mode in ["taker", "maker"]:
        args.mode = mode
        args.label = mode
        report = run_simulation(args)
        results[mode] = report
        print(f"\n{'='*35} {mode.upper()} {'='*35}")
        print_summary(report)
        save_report(report, label=mode)

    # Comparison
    t, m = results["taker"], results["maker"]
    print("\n" + "=" * 70)
    print("COMPARISON: TAKER vs MAKER")
    print("=" * 70)
    print(f"{'Metric':<30} {'Taker':>15} {'Maker':>15} {'Delta':>15}")
    print("-" * 75)
    print(f"{'Filled trades':<30} {t.filled_trades:>15,} {m.filled_trades:>15,} {m.filled_trades - t.filled_trades:>+15,}")
    print(f"{'Hit rate':<30} {t.hit_rate:>14.1%} {m.hit_rate:>14.1%} {(m.hit_rate - t.hit_rate):>+14.1%}")
    print(f"{'Total PnL':<30} {'$'+f'{t.total_pnl:,.2f}':>15} {'$'+f'{m.total_pnl:,.2f}':>15} {'$'+f'{m.total_pnl - t.total_pnl:+,.2f}':>15}")
    print(f"{'Max drawdown':<30} {'$'+f'{t.max_drawdown:,.2f}':>15} {'$'+f'{m.max_drawdown:,.2f}':>15} {'$'+f'{m.max_drawdown - t.max_drawdown:+,.2f}':>15}")
    print(f"{'Total fees':<30} {'$'+f'{t.total_fees:,.2f}':>15} {'$'+f'{m.total_fees:,.2f}':>15} {'$'+f'{m.total_fees - t.total_fees:+,.2f}':>15}")
    print(f"{'Final capital':<30} {'$'+f'{t.final_capital:,.2f}':>15} {'$'+f'{m.final_capital:,.2f}':>15} {'$'+f'{m.final_capital - t.final_capital:+,.2f}':>15}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Paper-trade simulator")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=str(DEFAULT_CONFIG), help="Config YAML path")
    common.add_argument("--markets", default=str(DEFAULT_MARKETS), help="Historical markets JSON path")
    common.add_argument("--cache", default=str(DEFAULT_CACHE), help="Claude cache JSON path")
    common.add_argument("--mode", choices=["taker", "maker"], help="Override execution mode")
    common.add_argument("--sizing", choices=["fixed_fraction", "kelly", "capped_kelly"], help="Override sizing method")
    common.add_argument("--capital", type=float, help="Override initial capital")
    common.add_argument("--seed", type=int, help="Override random seed")
    common.add_argument("--label", default=None, help="Label for output file")

    subparsers.add_parser("run", parents=[common], help="Run simulation")
    subparsers.add_parser("audit", parents=[common], help="Run + audit summary")
    subparsers.add_parser("compare", parents=[common], help="Compare taker vs maker")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "compare":
        cmd_compare(args)


if __name__ == "__main__":
    main()
