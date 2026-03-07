#!/usr/bin/env python3
"""Backtest velocity analysis: show ARR improvement from capital velocity sorting.

For the 532 resolved markets, compute:
1. Estimated resolution time (heuristic)
2. Actual resolution time (from end_date vs market data)
3. Capital velocity score per trade
4. ARR comparison: velocity-sorted top-5 vs taking all signals
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

# Add polymarket-bot/src to path for resolution_estimator import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "polymarket-bot"))

from src.resolution_estimator import (
    estimate_resolution_days,
    capital_velocity_score,
    BUCKET_1_4W,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_markets():
    path = os.path.join(DATA_DIR, "historical_markets.json")
    with open(path) as f:
        data = json.load(f)
    return data["markets"]


def load_claude_cache():
    path = os.path.join(DATA_DIR, "claude_cache.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def compute_actual_resolution_days(market: dict) -> Optional[float]:
    """Compute actual days from market creation to end_date.

    Since we don't have createdAt in the historical data, we approximate:
    - Use the end_date as the resolution date
    - For markets with explicit dates in their questions, that IS the resolution date
    - Return None if we can't determine it
    """
    end_date_str = market.get("end_date", "")
    if not end_date_str:
        return None

    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

    # We don't have creation date in historical data, so we estimate
    # resolution time relative to a reference point. For backtest purposes,
    # we treat end_date as "when it resolved" and use the question to
    # estimate how long the market was open.
    # For the velocity analysis, what matters is: estimated_days (our prediction)
    # vs the grouping behavior (do fast markets win more?)
    return None  # Will use estimated_days from heuristic instead


def simulate_trades(markets: list, claude_cache: dict, edge_threshold: float = 0.05,
                    position_size: float = 2.0) -> list[dict]:
    """Simulate trades with resolution time data attached.

    Mirrors the backtest engine logic but adds velocity metadata.
    """
    import hashlib

    trades = []
    entry_price = 0.50  # Simulated entry at 50/50

    for market in markets:
        question = market["question"]
        actual = market["actual_outcome"]
        end_date = market.get("end_date", "")

        # Get Claude estimate from cache
        cache_key = hashlib.sha256(question.encode()).hexdigest()[:16]
        cached = claude_cache.get(cache_key)
        if not cached:
            continue

        claude_prob = cached.get("probability", 0.5)

        # Estimate resolution time using text-based heuristics.
        # For backtest: we skip end_date (since all are in the past) and
        # rely on question-text parsing, which is what differentiates
        # fast-resolving from slow-resolving markets.
        #
        # For live trading, the scanner uses end_date (the primary signal).
        # Here we test whether text heuristics alone provide useful velocity
        # differentiation.
        res_est = estimate_resolution_days(
            question=question,
            end_date=None,  # Skip — all are historical/past dates
            category=None,
        )
        estimated_days = res_est["estimated_days"]
        resolution_bucket = res_est["bucket"]
        resolution_method = res_est["method"]

        # Compute edge
        edge = claude_prob - entry_price
        abs_edge = abs(edge)

        if abs_edge < edge_threshold:
            continue

        direction = "buy_yes" if edge > 0 else "buy_no"

        # Resolve trade
        if direction == "buy_yes":
            won = actual == "YES_WON"
            pnl = position_size * ((1.0 / entry_price) - 1) if won else -position_size
        else:
            won = actual == "NO_WON"
            pnl = position_size * ((1.0 / (1.0 - entry_price)) - 1) if won else -position_size

        # Capital velocity score
        vel_score = capital_velocity_score(abs_edge, estimated_days)

        trades.append({
            "question": question[:80],
            "direction": direction,
            "claude_prob": claude_prob,
            "actual": actual,
            "won": won,
            "pnl": round(pnl, 4),
            "edge": round(abs_edge, 4),
            "estimated_days": estimated_days,
            "resolution_bucket": resolution_bucket,
            "resolution_method": resolution_method,
            "velocity_score": round(vel_score, 2),
        })

    return trades


def analyze_velocity_impact(trades: list[dict], top_n: int = 5) -> dict:
    """Compare velocity-sorted top-N vs all trades.

    Simulates daily cycles where we pick top_n by velocity each cycle.
    """
    if not trades:
        return {"error": "no trades"}

    # === BASELINE: All trades ===
    total_trades = len(trades)
    baseline_wins = sum(1 for t in trades if t["won"])
    baseline_win_rate = baseline_wins / total_trades
    baseline_total_pnl = sum(t["pnl"] for t in trades)
    baseline_avg_pnl = baseline_total_pnl / total_trades

    # Baseline estimated avg resolution days
    baseline_avg_days = sum(t["estimated_days"] for t in trades) / total_trades

    # === VELOCITY-SORTED TOP N ===
    # Sort by velocity score, take top N
    sorted_trades = sorted(trades, key=lambda t: t["velocity_score"], reverse=True)
    velocity_top = sorted_trades[:top_n * (total_trades // top_n)]  # Simulate picking top N per cycle
    if not velocity_top:
        velocity_top = sorted_trades[:top_n]

    velocity_wins = sum(1 for t in velocity_top if t["won"])
    velocity_win_rate = velocity_wins / len(velocity_top) if velocity_top else 0
    velocity_total_pnl = sum(t["pnl"] for t in velocity_top)
    velocity_avg_pnl = velocity_total_pnl / len(velocity_top) if velocity_top else 0
    velocity_avg_days = sum(t["estimated_days"] for t in velocity_top) / len(velocity_top)

    # === VELOCITY TOP-5 PER SIMULATED CYCLE ===
    # Group trades into cycles of len(trades)/cycles and pick top 5 from each
    cycle_size = 20  # Assume ~20 signals per cycle (matches live bot behavior)
    cycles = [trades[i:i + cycle_size] for i in range(0, len(trades), cycle_size)]

    velocity_picked = []
    for cycle in cycles:
        cycle_sorted = sorted(cycle, key=lambda t: t["velocity_score"], reverse=True)
        velocity_picked.extend(cycle_sorted[:top_n])

    if velocity_picked:
        vp_wins = sum(1 for t in velocity_picked if t["won"])
        vp_win_rate = vp_wins / len(velocity_picked)
        vp_total_pnl = sum(t["pnl"] for t in velocity_picked)
        vp_avg_pnl = vp_total_pnl / len(velocity_picked)
        vp_avg_days = sum(t["estimated_days"] for t in velocity_picked) / len(velocity_picked)
    else:
        vp_wins = vp_win_rate = vp_total_pnl = vp_avg_pnl = vp_avg_days = 0

    # === ARR CALCULATIONS ===
    # ARR = (avg_pnl_per_trade * trades_per_day * 365 - infra_annual) / capital
    capital = 75.0
    infra_annual = 240.0
    trades_per_day = 5  # base case

    # Baseline ARR (all trades, trades_per_day)
    baseline_arr_daily_gross = baseline_avg_pnl * trades_per_day
    baseline_arr_annual = baseline_arr_daily_gross * 365 - infra_annual
    baseline_arr_pct = (baseline_arr_annual / capital) * 100

    # Velocity-adjusted ARR: faster resolution means capital turns over faster
    # If velocity-picked trades resolve in avg N days, we can do capital/N turns per position
    # Effective trades/day with velocity = trades_per_day * (baseline_avg_days / velocity_avg_days)
    if vp_avg_days > 0:
        velocity_multiplier = baseline_avg_days / vp_avg_days
        # Cap the multiplier at 3x — can't realistically redeploy capital infinitely fast
        # (constrained by market availability, slippage, API rate limits)
        velocity_multiplier = min(velocity_multiplier, 3.0)
        velocity_effective_trades = trades_per_day * velocity_multiplier
    else:
        velocity_multiplier = 1.0
        velocity_effective_trades = trades_per_day

    velocity_arr_daily_gross = vp_avg_pnl * velocity_effective_trades
    velocity_arr_annual = velocity_arr_daily_gross * 365 - infra_annual
    velocity_arr_pct = (velocity_arr_annual / capital) * 100

    arr_improvement_pct = velocity_arr_pct - baseline_arr_pct

    # === BUCKET ANALYSIS ===
    bucket_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "avg_edge": 0.0})
    for t in trades:
        b = t["resolution_bucket"]
        bucket_stats[b]["count"] += 1
        if t["won"]:
            bucket_stats[b]["wins"] += 1
        bucket_stats[b]["pnl"] += t["pnl"]
        bucket_stats[b]["avg_edge"] += t["edge"]

    for b, stats in bucket_stats.items():
        if stats["count"] > 0:
            stats["win_rate"] = stats["wins"] / stats["count"]
            stats["avg_pnl"] = stats["pnl"] / stats["count"]
            stats["avg_edge"] = stats["avg_edge"] / stats["count"]

    return {
        "baseline": {
            "total_trades": total_trades,
            "win_rate": round(baseline_win_rate, 4),
            "total_pnl": round(baseline_total_pnl, 2),
            "avg_pnl": round(baseline_avg_pnl, 4),
            "avg_resolution_days": round(baseline_avg_days, 1),
            "arr_pct": round(baseline_arr_pct, 1),
        },
        "velocity_top_n_global": {
            "trades_selected": len(velocity_top),
            "win_rate": round(velocity_win_rate, 4),
            "total_pnl": round(velocity_total_pnl, 2),
            "avg_pnl": round(velocity_avg_pnl, 4),
            "avg_resolution_days": round(velocity_avg_days, 1),
        },
        "velocity_top_5_per_cycle": {
            "trades_selected": len(velocity_picked),
            "win_rate": round(vp_win_rate, 4),
            "total_pnl": round(vp_total_pnl, 2),
            "avg_pnl": round(vp_avg_pnl, 4),
            "avg_resolution_days": round(vp_avg_days, 1),
            "velocity_multiplier": round(velocity_multiplier, 2),
            "effective_trades_per_day": round(velocity_effective_trades, 1),
            "arr_pct": round(velocity_arr_pct, 1),
        },
        "arr_improvement": {
            "baseline_arr_pct": round(baseline_arr_pct, 1),
            "velocity_arr_pct": round(velocity_arr_pct, 1),
            "improvement_pct": round(arr_improvement_pct, 1),
            "improvement_relative": f"{(arr_improvement_pct / abs(baseline_arr_pct) * 100) if baseline_arr_pct != 0 else 0:.0f}%",
        },
        "by_resolution_bucket": {
            b: {
                "count": s["count"],
                "win_rate": round(s.get("win_rate", 0), 4),
                "avg_pnl": round(s.get("avg_pnl", 0), 4),
                "total_pnl": round(s["pnl"], 2),
                "avg_edge": round(s.get("avg_edge", 0), 4),
            }
            for b, s in sorted(bucket_stats.items())
        },
        "top_10_velocity_trades": [
            {
                "question": t["question"],
                "direction": t["direction"],
                "edge": t["edge"],
                "estimated_days": t["estimated_days"],
                "velocity_score": t["velocity_score"],
                "won": t["won"],
                "pnl": t["pnl"],
            }
            for t in sorted(trades, key=lambda t: t["velocity_score"], reverse=True)[:10]
        ],
    }


def print_report(results: dict):
    """Pretty-print the velocity analysis."""
    baseline = results["baseline"]
    vp = results["velocity_top_5_per_cycle"]
    arr = results["arr_improvement"]

    print("\n" + "=" * 70)
    print("  CAPITAL VELOCITY BACKTEST ANALYSIS")
    print("=" * 70)

    print(f"\n  BASELINE (all trades)")
    print(f"    Trades:              {baseline['total_trades']}")
    print(f"    Win rate:            {baseline['win_rate']:.1%}")
    print(f"    Avg P&L/trade:       ${baseline['avg_pnl']:+.4f}")
    print(f"    Avg resolution:      {baseline['avg_resolution_days']:.1f} days")
    print(f"    ARR:                 {baseline['arr_pct']:+.1f}%")

    print(f"\n  VELOCITY TOP-5 PER CYCLE")
    print(f"    Trades selected:     {vp['trades_selected']}")
    print(f"    Win rate:            {vp['win_rate']:.1%}")
    print(f"    Avg P&L/trade:       ${vp['avg_pnl']:+.4f}")
    print(f"    Avg resolution:      {vp['avg_resolution_days']:.1f} days")
    print(f"    Velocity multiplier: {vp['velocity_multiplier']:.2f}x")
    print(f"    Effective trades/day:{vp['effective_trades_per_day']:.1f}")
    print(f"    ARR:                 {vp['arr_pct']:+.1f}%")

    print(f"\n  ARR IMPROVEMENT")
    print(f"    Baseline ARR:        {arr['baseline_arr_pct']:+.1f}%")
    print(f"    Velocity ARR:        {arr['velocity_arr_pct']:+.1f}%")
    print(f"    Improvement:         {arr['improvement_pct']:+.1f}% ({arr['improvement_relative']})")

    print(f"\n  BY RESOLUTION BUCKET")
    print(f"    {'Bucket':<10} {'Count':>6} {'Win Rate':>10} {'Avg P&L':>10} {'Total P&L':>10} {'Avg Edge':>10}")
    print(f"    {'-'*56}")
    for bucket, stats in results["by_resolution_bucket"].items():
        print(f"    {bucket:<10} {stats['count']:>6} {stats['win_rate']:>9.1%} "
              f"${stats['avg_pnl']:>+8.4f} ${stats['total_pnl']:>+8.2f} {stats['avg_edge']:>9.1%}")

    print(f"\n  TOP 10 VELOCITY TRADES")
    for t in results["top_10_velocity_trades"]:
        status = "WIN " if t["won"] else "LOSS"
        print(f"    [{status}] vel={t['velocity_score']:>8.1f} edge={t['edge']:.1%} "
              f"days={t['estimated_days']:>5.1f} ${t['pnl']:+.2f} | {t['question']}")

    print("=" * 70)


def main():
    print("Loading markets and Claude cache...")
    markets = load_markets()
    claude_cache = load_claude_cache()
    print(f"  {len(markets)} markets, {len(claude_cache)} cached estimates")

    print("\nSimulating trades with velocity data...")
    trades = simulate_trades(markets, claude_cache)
    print(f"  {len(trades)} trades simulated")

    print("\nAnalyzing velocity impact...")
    results = analyze_velocity_impact(trades, top_n=5)

    # Save results
    results_path = os.path.join(DATA_DIR, "velocity_analysis.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {results_path}")

    print_report(results)

    return results


if __name__ == "__main__":
    main()
