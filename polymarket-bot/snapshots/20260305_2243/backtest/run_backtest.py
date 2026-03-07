#!/usr/bin/env python3
"""CLI entry point for the backtest system."""
import argparse
import json
import os
import sys
import time

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(__file__))

from collector import collect
from engine import BacktestEngine, print_report
from validation import run_full_validation, print_validation_report


def cmd_collect(args):
    """Collect resolved markets from Gamma API."""
    print(f"Collecting {args.count} resolved Yes/No markets...")
    result = collect(target_count=args.count)
    print(f"\nDone: {result['total_markets']} markets collected")
    print(f"  YES won: {result['yes_won']}")
    print(f"  NO won: {result['no_won']}")


def cmd_run(args):
    """Run backtest on collected data."""
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY env var or pass --api-key")
        sys.exit(1)

    engine = BacktestEngine(
        api_key=api_key,
        edge_threshold=args.threshold,
        position_size=args.size,
        starting_capital=args.capital,
    )

    print(f"Running backtest (threshold={args.threshold:.0%}, size=${args.size}, capital=${args.capital})...")
    results = engine.run(max_markets=args.max_markets)
    print_report(results)


def cmd_report(args):
    """Print report from existing results."""
    results_path = os.path.join(os.path.dirname(__file__), "data", "backtest_results.json")
    if not os.path.exists(results_path):
        print("No results found. Run --run first.")
        sys.exit(1)

    with open(results_path) as f:
        results = json.load(f)
    print_report(results)


def cmd_continuous(args):
    """Run collect + backtest on a loop."""
    interval = args.interval
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY env var or pass --api-key")
        sys.exit(1)

    print(f"Continuous mode: collect + backtest every {interval}s")
    while True:
        try:
            print(f"\n{'='*40} {time.strftime('%Y-%m-%d %H:%M:%S')} {'='*40}")

            # Collect newly resolved markets
            result = collect(target_count=args.count)
            print(f"Markets: {result['total_markets']}")

            # Run backtest
            engine = BacktestEngine(
                api_key=api_key,
                edge_threshold=args.threshold,
                position_size=args.size,
                starting_capital=args.capital,
            )
            results = engine.run()
            print_report(results)

            # Update strategy report if path provided
            if args.report_path:
                _update_strategy_report(args.report_path, results)

        except Exception as e:
            print(f"Error in continuous loop: {e}")

        print(f"\nSleeping {interval}s...")
        time.sleep(interval)


def cmd_validate(args):
    """Run full validation framework."""
    print(f"Running validation framework (correcting for {args.variants} strategy variants)...")
    results = run_full_validation(num_strategy_variants=args.variants)
    print_validation_report(results)

    if args.save:
        import json
        out_path = os.path.join(os.path.dirname(__file__), "data", "validation_results.json")
        save_results = json.loads(json.dumps(results, default=str))
        with open(out_path, "w") as f:
            json.dump(save_results, f, indent=2)
        print(f"\nSaved to {out_path}")


def _update_strategy_report(report_path: str, results: dict):
    """Update STRATEGY_REPORT.md with latest backtest numbers."""
    if not os.path.exists(report_path):
        return

    s = results["summary"]
    arr = results["arr_estimate"]

    update_block = f"""### Latest Backtest Results (auto-updated {results['run_at']})

| Metric | Value |
|--------|-------|
| Markets backtested | {results['markets_analyzed']} |
| Total trades simulated | {results['total_trades']} |
| Win rate | {s['win_rate']:.1%} |
| Avg Brier score | {s['avg_brier_score']:.4f} |
| Avg edge | {s['avg_edge']:.1%} |
| Total simulated P&L | ${s['total_pnl']:+.2f} |
| Max drawdown | ${s['max_drawdown']:.2f} |
| **Backtest ARR %** | **{arr['arr_pct']:+.1f}%** |
"""

    with open(report_path) as f:
        content = f.read()

    marker = "### Latest Backtest Results"
    if marker in content:
        # Replace existing block
        start = content.index(marker)
        # Find next ### or --- or end
        end = len(content)
        for sep in ["### ", "---", "## "]:
            idx = content.find(sep, start + len(marker))
            if idx > 0 and idx < end:
                end = idx
        content = content[:start] + update_block + "\n" + content[end:]
    else:
        # Insert after "### Live Performance Snapshot"
        insert_after = "### Live Performance Snapshot"
        if insert_after in content:
            idx = content.index(insert_after)
            # Find the next ### or ---
            next_section = len(content)
            for sep in ["### ", "---"]:
                search_start = idx + len(insert_after)
                found = content.find(sep, search_start)
                if found > 0 and found < next_section:
                    next_section = found
            content = content[:next_section] + update_block + "\n" + content[next_section:]
        else:
            # Append
            content += "\n" + update_block

    with open(report_path, "w") as f:
        f.write(content)

    print(f"Updated {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Historical Backtest")
    sub = parser.add_subparsers(dest="command")

    # Collect
    p_collect = sub.add_parser("collect", help="Fetch resolved markets")
    p_collect.add_argument("--count", type=int, default=500)

    # Run
    p_run = sub.add_parser("run", help="Run backtest")
    p_run.add_argument("--api-key", type=str, default="")
    p_run.add_argument("--threshold", type=float, default=0.05)
    p_run.add_argument("--size", type=float, default=2.0)
    p_run.add_argument("--capital", type=float, default=75.0)
    p_run.add_argument("--max-markets", type=int, default=0)

    # Report
    p_report = sub.add_parser("report", help="Print saved results")

    # Continuous
    p_cont = sub.add_parser("continuous", help="Continuous collect+backtest loop")
    p_cont.add_argument("--api-key", type=str, default="")
    p_cont.add_argument("--interval", type=int, default=21600, help="Seconds between runs (default 6h)")
    p_cont.add_argument("--count", type=int, default=500)
    p_cont.add_argument("--threshold", type=float, default=0.05)
    p_cont.add_argument("--size", type=float, default=2.0)
    p_cont.add_argument("--capital", type=float, default=75.0)
    p_cont.add_argument("--report-path", type=str, default="")

    # Validate
    p_validate = sub.add_parser("validate", help="Run full validation framework (DSR, Brier decomp, significance)")
    p_validate.add_argument("--variants", type=int, default=10, help="Number of strategy variants tested")
    p_validate.add_argument("--save", action="store_true", help="Save validation results to JSON")

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "continuous":
        cmd_continuous(args)
    elif args.command == "validate":
        cmd_validate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
