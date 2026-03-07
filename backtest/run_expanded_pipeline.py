#!/usr/bin/env python3
"""Run the full expanded backtest pipeline after Claude cache is populated.

Steps:
1. Run backtest engine (uses cached estimates)
2. Run CalibrationV2 with new 70/30 split on larger dataset
3. Run strategy variants comparison
4. Run Monte Carlo with 10,000 paths
5. Run exit strategy backtest
6. Generate all charts
7. Generate RESULTS.md with 532 vs expanded comparison
"""
import json
import os
import sys
import time

# Ensure imports work
BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKTEST_DIR)

DATA_DIR = os.path.join(BACKTEST_DIR, "data")
RESULTS_DIR = os.path.join(BACKTEST_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def step_1_check_data():
    """Verify we have enough data."""
    import hashlib

    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    n_markets = markets["total_markets"]
    n_cache = len(cache)
    cached = sum(
        1 for m in markets["markets"]
        if hashlib.sha256(m["question"].encode()).hexdigest()[:16] in cache
    )

    print(f"\n{'='*60}")
    print(f"  STEP 1: DATA CHECK")
    print(f"{'='*60}")
    print(f"  Markets:     {n_markets}")
    print(f"  Cache:       {n_cache}")
    print(f"  Matched:     {cached}")
    print(f"  Missing:     {n_markets - cached}")

    if cached < 1000:
        print(f"\n  WARNING: Only {cached} markets have Claude estimates.")
        print(f"  Need to run backtest engine first to populate cache.")
        return False

    return True


def step_2_run_backtest():
    """Run backtest engine (uses cached estimates)."""
    from engine import BacktestEngine, print_report

    print(f"\n{'='*60}")
    print(f"  STEP 2: BACKTEST ENGINE")
    print(f"{'='*60}")

    engine = BacktestEngine(
        edge_threshold=0.05,
        position_size=2.0,
        starting_capital=75.0,
    )
    results = engine.run()
    print_report(results)
    return results


def step_3_calibration():
    """Run CalibrationV2 with new train/test split."""
    from calibration import CalibrationV2, load_calibration_samples, CalibrationCorrector

    print(f"\n{'='*60}")
    print(f"  STEP 3: CALIBRATION V2")
    print(f"{'='*60}")

    corrector = CalibrationCorrector()
    corrector.print_mapping()
    return corrector


def step_4_strategy_variants():
    """Run all strategy variants."""
    print(f"\n{'='*60}")
    print(f"  STEP 4: STRATEGY VARIANTS")
    print(f"{'='*60}")

    from strategy_variants import run_all_variants
    return run_all_variants()


def step_5_monte_carlo():
    """Run Monte Carlo with 10,000 paths."""
    from monte_carlo import load_empirical_trades, run_simulation, print_simulation_report

    print(f"\n{'='*60}")
    print(f"  STEP 5: MONTE CARLO (10,000 paths)")
    print(f"{'='*60}")

    trades = load_empirical_trades()
    print(f"  Loaded {len(trades)} empirical trades")

    results = run_simulation(
        trades,
        starting_capital=75.0,
        trades_per_day=5,
        num_paths=10000,
        use_kelly=True,
    )
    print_simulation_report(results)

    # Save
    with open(os.path.join(DATA_DIR, "monte_carlo_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Saved Monte Carlo results")

    return results


def step_6_exit_backtest():
    """Run exit strategy backtest."""
    from exit_backtest import run_exit_backtest

    print(f"\n{'='*60}")
    print(f"  STEP 6: EXIT STRATEGY BACKTEST")
    print(f"{'='*60}")

    return run_exit_backtest()


def step_7_charts():
    """Generate all charts."""
    from generate_charts import generate_all

    print(f"\n{'='*60}")
    print(f"  STEP 7: CHARTS")
    print(f"{'='*60}")

    generate_all()


def step_8_results_md(backtest_results, mc_results, exit_results):
    """Generate RESULTS.md comparing 532 vs expanded dataset."""
    print(f"\n{'='*60}")
    print(f"  STEP 8: RESULTS.MD")
    print(f"{'='*60}")

    # Load 532-market baseline for comparison
    old_baseline = {
        "markets": 532,
        "total_trades": 3302,
        "win_rate": 0.6281,
        "avg_brier": 0.2391,
        "avg_edge": 0.3171,
        "total_pnl": 5425.76,
        "max_drawdown": 50.00,
        "arr_pct": 3623.6,
    }

    new_s = backtest_results["summary"]
    new_a = backtest_results["arr_estimate"]

    # Load calibration v2 results
    cal_path = os.path.join(DATA_DIR, "calibration_v2_results.json")
    cal_results = {}
    if os.path.exists(cal_path):
        with open(cal_path) as f:
            cal_results = json.load(f)

    # Load strategy comparison
    strat_path = os.path.join(DATA_DIR, "strategy_comparison.json")
    strat_results = {}
    if os.path.exists(strat_path):
        with open(strat_path) as f:
            strat_results = json.load(f)

    # Build RESULTS.md
    lines = []
    lines.append("# Expanded Backtest Results")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    lines.append("## Dataset Comparison: 532 vs Expanded")
    lines.append("")
    lines.append(f"| Metric | 532 Markets | {backtest_results['markets_analyzed']} Markets | Delta |")
    lines.append("|--------|-------------|------------|-------|")

    def delta_str(old, new, fmt=".1f", pct=False):
        d = new - old
        suffix = "%" if pct else ""
        return f"{d:+{fmt}}{suffix}"

    lines.append(f"| Markets | {old_baseline['markets']} | {backtest_results['markets_analyzed']} | +{backtest_results['markets_analyzed'] - old_baseline['markets']} |")
    lines.append(f"| Total Trades | {old_baseline['total_trades']:,} | {backtest_results['total_trades']:,} | {delta_str(old_baseline['total_trades'], backtest_results['total_trades'], 'd')} |")
    lines.append(f"| Win Rate | {old_baseline['win_rate']:.1%} | {new_s['win_rate']:.1%} | {delta_str(old_baseline['win_rate']*100, new_s['win_rate']*100, '.1f')}pp |")
    lines.append(f"| Avg Brier Score | {old_baseline['avg_brier']:.4f} | {new_s['avg_brier_score']:.4f} | {delta_str(old_baseline['avg_brier'], new_s['avg_brier_score'], '.4f')} |")
    lines.append(f"| Avg Edge | {old_baseline['avg_edge']:.1%} | {new_s['avg_edge']:.1%} | {delta_str(old_baseline['avg_edge']*100, new_s['avg_edge']*100, '.1f')}pp |")
    lines.append(f"| Total P&L | ${old_baseline['total_pnl']:,.2f} | ${new_s['total_pnl']:,.2f} | ${new_s['total_pnl'] - old_baseline['total_pnl']:+,.2f} |")
    lines.append(f"| Max Drawdown | ${old_baseline['max_drawdown']:.2f} | ${new_s['max_drawdown']:.2f} | ${new_s['max_drawdown'] - old_baseline['max_drawdown']:+.2f} |")
    lines.append(f"| ARR % | {old_baseline['arr_pct']:+.1f}% | {new_a['arr_pct']:+.1f}% | {new_a['arr_pct'] - old_baseline['arr_pct']:+.1f}% |")
    lines.append("")

    # Calibration section
    if cal_results:
        cal_data = cal_results.get("calibration", {})
        lines.append("## Calibration V2 (Platt Scaling)")
        lines.append("")
        if cal_data:
            lines.append(f"- Method: {cal_data.get('chosen_method', 'platt').upper()}")
            lines.append(f"- Train/Test split: {cal_data.get('n_train', '?')}/{cal_data.get('n_test', '?')}")
            test = cal_data.get("test_set", {})
            lines.append(f"- Test Brier (raw): {test.get('brier_raw', '?')}")
            lines.append(f"- Test Brier (calibrated): {test.get('brier_platt', '?')}")
            imp = cal_data.get("improvement", {})
            lines.append(f"- Improvement: {imp.get('best_vs_raw', '?')}")
        lines.append("")

    # Monte Carlo section
    if mc_results:
        lines.append("## Monte Carlo Simulation (10,000 paths)")
        lines.append("")
        fc = mc_results["final_capital"]
        risk = mc_results["risk"]
        arr = mc_results["arr"]
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Median final capital | ${fc['median']:,.2f} |")
        lines.append(f"| 5th percentile | ${fc['p5']:,.2f} |")
        lines.append(f"| 95th percentile | ${fc['p95']:,.2f} |")
        lines.append(f"| P(ruin) | {risk['probability_of_ruin']:.1%} |")
        lines.append(f"| P(50% drawdown) | {risk['probability_50pct_drawdown']:.1%} |")
        lines.append(f"| Median ARR | {arr['median_arr']:+.1f}% |")
        lines.append(f"| 5th pct ARR | {arr['p5_arr']:+.1f}% |")
        lines.append(f"| 95th pct ARR | {arr['p95_arr']:+.1f}% |")
        lines.append("")

    # Exit strategy section
    if exit_results:
        lines.append("## Exit Strategy Comparison")
        lines.append("")
        hold = exit_results["hold_to_resolution"]
        early = exit_results["early_exit"]
        imp = exit_results["improvement"]
        lines.append(f"| Metric | Hold to Resolution | Early Exit | Delta |")
        lines.append(f"|--------|-------------------|------------|-------|")
        lines.append(f"| Win Rate | {hold['win_rate']:.1%} | {early['win_rate']:.1%} | {imp['win_rate_delta']:+.1%} |")
        lines.append(f"| Total P&L | ${hold['total_pnl']:+.2f} | ${early['total_pnl']:+.2f} | ${imp['pnl_delta']:+.2f} |")
        lines.append(f"| Avg Hold (days) | {hold['avg_hold_days']:.1f} | {early['avg_hold_days']:.1f} | {imp['avg_hold_reduction_days']:+.1f} |")
        lines.append(f"| Max Drawdown | ${hold['max_drawdown']:.2f} | ${early['max_drawdown']:.2f} | |")
        lines.append(f"| Capital Velocity | 1.0x | {imp['capital_velocity_multiplier']:.2f}x | |")
        lines.append(f"| ARR % | {hold['arr_pct']:+.1f}% | {early['arr_pct']:+.1f}% | {imp['arr_delta']:+.1f}% |")
        lines.append("")

        lines.append("### Exit Reason Breakdown")
        lines.append("")
        lines.append("| Reason | Count | Win Rate | Avg P&L | Total P&L |")
        lines.append("|--------|-------|----------|---------|-----------|")
        for reason, stats in sorted(exit_results.get("exit_reasons", {}).items()):
            lines.append(f"| {reason} | {stats['count']} | {stats['win_rate']:.1%} | ${stats['avg_pnl']:+.4f} | ${stats['total_pnl']:+.2f} |")
        lines.append("")

    # Strategy variants table
    if strat_results:
        lines.append("## Strategy Variants")
        lines.append("")
        lines.append("| Variant | Trades | Win Rate | P&L | Brier | ARR@5 |")
        lines.append("|---------|--------|----------|-----|-------|-------|")
        for name, stats in strat_results.items():
            lines.append(f"| {name} | {stats['trades']} | {stats['win_rate']:.1%} | ${stats['total_pnl']:+.2f} | {stats['brier']:.4f} | {stats['arr_5']:+.0f}% |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by `backtest/run_expanded_pipeline.py`*")

    content = "\n".join(lines)
    results_path = os.path.join(BACKTEST_DIR, "RESULTS.md")
    with open(results_path, "w") as f:
        f.write(content)
    print(f"  Saved {results_path}")

    return results_path


def main():
    print("\n" + "#" * 60)
    print("  EXPANDED BACKTEST PIPELINE")
    print("#" * 60)

    if not step_1_check_data():
        print("\nAborting: insufficient data. Run backtest engine first.")
        sys.exit(1)

    backtest_results = step_2_run_backtest()
    step_3_calibration()
    step_4_strategy_variants()
    mc_results = step_5_monte_carlo()
    exit_results = step_6_exit_backtest()
    step_7_charts()
    step_8_results_md(backtest_results, mc_results, exit_results)

    print("\n" + "#" * 60)
    print("  PIPELINE COMPLETE")
    print("#" * 60)


if __name__ == "__main__":
    main()
