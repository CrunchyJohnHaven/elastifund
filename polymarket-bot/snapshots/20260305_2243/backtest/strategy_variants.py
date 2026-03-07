"""Test multiple strategy variants against 532-market backtest data.

Uses CalibrationV2 with out-of-sample validation (70/30 train/test split).

Variants:
1. Baseline: symmetric 5% threshold, flat $2 sizing
2. NO-only: only take buy_no trades
3. Asymmetric: 5% threshold for NO, 15% for YES
4. High-threshold: 10% symmetric
5. Calibrated (v2): Platt-scaled calibration from train split
6. Calibrated + asymmetric
7. Calibrated + confidence-weighted sizing
"""
from __future__ import annotations

import hashlib
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_data():
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)
    return markets, cache


def simulate_strategy(markets, cache, config):
    """Run a strategy variant and return metrics.

    config keys:
        yes_threshold: minimum edge to take buy_yes trade
        no_threshold: minimum edge to take buy_no trade
        entry_price: simulated entry price
        size: position size
        use_calibration: bool, apply calibration correction
        calibrator: CalibrationV2 or CalibrationCorrector instance (if use_calibration)
        use_confidence_sizing: bool, apply confidence-weighted sizing
    """
    yes_thresh = config.get("yes_threshold", 0.05)
    no_thresh = config.get("no_threshold", 0.05)
    entry = config.get("entry_price", 0.50)
    size = config.get("size", 2.0)
    use_cal = config.get("use_calibration", False)
    calibrator = config.get("calibrator", None)
    use_conf_sizing = config.get("use_confidence_sizing", False)

    trades = []
    brier_scores = []

    for m in markets:
        question = m["question"]
        actual = m["actual_outcome"]
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        raw_prob = est["probability"]
        prob = calibrator.correct(raw_prob) if use_cal and calibrator else raw_prob

        actual_binary = 1.0 if actual == "YES_WON" else 0.0
        brier_scores.append((prob - actual_binary) ** 2)

        edge = prob - entry
        abs_edge = abs(edge)

        # Determine direction and check threshold
        if edge > 0:
            direction = "buy_yes"
            if abs_edge < yes_thresh:
                continue
        else:
            direction = "buy_no"
            if abs_edge < no_thresh:
                continue

        # Apply confidence-weighted sizing
        trade_size = size
        if use_conf_sizing and calibrator and hasattr(calibrator, 'get_sizing_multiplier'):
            multiplier = calibrator.get_sizing_multiplier(raw_prob)
            trade_size = size * multiplier

        # Resolve trade
        if direction == "buy_yes":
            won = actual == "YES_WON"
            pnl = (trade_size / entry) - trade_size if won else -trade_size
        else:
            no_price = 1.0 - entry
            won = actual == "NO_WON"
            pnl = (trade_size / no_price) - trade_size if won else -trade_size

        trades.append({
            "won": won, "pnl": pnl, "direction": direction,
            "prob": prob, "edge": abs_edge, "size": trade_size,
        })

    # Compute metrics
    total = len(trades)
    if total == 0:
        return {"trades": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
                "brier": 0, "max_drawdown": 0, "yes_trades": 0, "yes_win_rate": 0,
                "no_trades": 0, "no_win_rate": 0, "arr_3": 0, "arr_5": 0, "arr_8": 0}

    wins = sum(1 for t in trades if t["won"])
    total_pnl = sum(t["pnl"] for t in trades)
    avg_pnl = total_pnl / total

    yes_trades = [t for t in trades if t["direction"] == "buy_yes"]
    no_trades = [t for t in trades if t["direction"] == "buy_no"]
    yes_wins = sum(1 for t in yes_trades if t["won"]) if yes_trades else 0
    no_wins = sum(1 for t in no_trades if t["won"]) if no_trades else 0

    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5

    # ARR at different trade frequencies
    def arr(tpd):
        monthly_net = (avg_pnl * tpd * 30) - 20
        return (monthly_net * 12 / 75) * 100

    # Max drawdown
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t["pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        "trades": total,
        "win_rate": wins / total,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 4),
        "brier": round(avg_brier, 4),
        "max_drawdown": round(max_dd, 2),
        "yes_trades": len(yes_trades),
        "yes_win_rate": yes_wins / len(yes_trades) if yes_trades else 0,
        "no_trades": len(no_trades),
        "no_win_rate": no_wins / len(no_trades) if no_trades else 0,
        "arr_3": round(arr(3), 0),
        "arr_5": round(arr(5), 0),
        "arr_8": round(arr(8), 0),
    }


def run_all_variants():
    """Run all strategy variants and compare."""
    from calibration import CalibrationCorrector

    markets, cache = load_data()
    calibrator = CalibrationCorrector()

    variants = {
        "1. Baseline (5% symmetric)": {
            "yes_threshold": 0.05, "no_threshold": 0.05,
        },
        "2. NO-only": {
            "yes_threshold": 999.0, "no_threshold": 0.05,
        },
        "3. Asymmetric (YES 15%, NO 5%)": {
            "yes_threshold": 0.15, "no_threshold": 0.05,
        },
        "4. Asymmetric (YES 20%, NO 5%)": {
            "yes_threshold": 0.20, "no_threshold": 0.05,
        },
        "5. High threshold (10% symmetric)": {
            "yes_threshold": 0.10, "no_threshold": 0.10,
        },
        "6. Calibrated v2 (5% symmetric)": {
            "yes_threshold": 0.05, "no_threshold": 0.05,
            "use_calibration": True, "calibrator": calibrator,
        },
        "7. Calibrated v2 + NO-only": {
            "yes_threshold": 999.0, "no_threshold": 0.05,
            "use_calibration": True, "calibrator": calibrator,
        },
        "8. Calibrated v2 + Asymmetric (YES 15%, NO 5%)": {
            "yes_threshold": 0.15, "no_threshold": 0.05,
            "use_calibration": True, "calibrator": calibrator,
        },
        "9. Calibrated v2 + Confidence Sizing": {
            "yes_threshold": 0.05, "no_threshold": 0.05,
            "use_calibration": True, "calibrator": calibrator,
            "use_confidence_sizing": True,
        },
        "10. Cal v2 + Asym + Confidence Sizing": {
            "yes_threshold": 0.15, "no_threshold": 0.05,
            "use_calibration": True, "calibrator": calibrator,
            "use_confidence_sizing": True,
        },
    }

    print("\n" + "=" * 130)
    print("  STRATEGY VARIANT COMPARISON (entry=0.50, CalibrationV2 — out-of-sample)")
    print("=" * 130)
    print(f"  {'Variant':<50s} {'Trades':>6s} {'WinRate':>8s} {'P&L':>8s} "
          f"{'AvgPnL':>8s} {'Brier':>6s} {'MaxDD':>6s} "
          f"{'YES_WR':>7s} {'NO_WR':>7s} {'ARR@5':>7s}")
    print("-" * 130)

    all_results = {}
    for name, config in variants.items():
        config["entry_price"] = 0.50
        r = simulate_strategy(markets, cache, config)
        all_results[name] = r
        print(f"  {name:<50s} {r['trades']:6d} {r['win_rate']:7.1%} ${r['total_pnl']:>7.2f} "
              f"${r['avg_pnl']:>7.4f} {r['brier']:6.4f} ${r['max_drawdown']:>5.2f} "
              f"{r['yes_win_rate']:6.1%} {r['no_win_rate']:6.1%} {r['arr_5']:>6.0f}%")

    # Find best variant by ARR@5
    best = max(all_results.items(), key=lambda x: x[1]["arr_5"])
    print(f"\n  BEST VARIANT: {best[0]}")
    print(f"    Win Rate: {best[1]['win_rate']:.1%}")
    print(f"    ARR @5/day: {best[1]['arr_5']:+.0f}%")
    print(f"    Total P&L: ${best[1]['total_pnl']:+.2f}")
    print(f"    Brier: {best[1]['brier']:.4f}")

    # Calibration v2 info
    print(f"\n  CALIBRATION V2 INFO:")
    cal_results = calibrator._results
    print(f"    Method: {cal_results['chosen_method'].upper()}")
    print(f"    Train/Test: {cal_results['n_train']}/{cal_results['n_test']}")
    print(f"    Test Brier (raw):   {cal_results['test_set']['brier_raw']:.4f}")
    method = cal_results['chosen_method']
    print(f"    Test Brier (calib): {cal_results['test_set'][f'brier_{method}']:.4f}")
    print(f"    Improvement:        {cal_results['improvement']['best_vs_raw']:+.4f}")

    print("=" * 130)

    # Save results
    save_results = {k: v for k, v in all_results.items()}
    with open(os.path.join(DATA_DIR, "strategy_comparison.json"), "w") as f:
        json.dump(save_results, f, indent=2, default=str)

    return all_results


if __name__ == "__main__":
    run_all_variants()
