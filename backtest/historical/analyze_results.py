#!/usr/bin/env python3
"""[Historical Utility] Analyze backtest results and compute realistic ARR.

Prefer `python3 -m backtest.run_combined` for current canonical reporting.
"""
from __future__ import annotations

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def analyze():
    with open(os.path.join(DATA_DIR, "backtest_results.json")) as f:
        results = json.load(f)

    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets_data = json.load(f)

    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    markets = markets_data["markets"]

    # Compute "realistic single-trade" metrics
    # For each market, pick the MIDDLE entry price (0.50) as the most likely price
    # the bot would encounter
    import hashlib

    single_trades = []
    for m in markets:
        question = m["question"]
        actual = m["actual_outcome"]
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        claude_prob = est["probability"]
        confidence = est.get("confidence", "medium")

        # Simulate at 0.50 entry price (market midpoint)
        entry = 0.50
        edge = claude_prob - entry
        abs_edge = abs(edge)

        if abs_edge < 0.05:
            continue  # Below threshold

        if edge > 0:
            direction = "buy_yes"
        else:
            direction = "buy_no"

        size = 2.0  # Fixed $2 position

        if direction == "buy_yes":
            if actual == "YES_WON":
                pnl = (size / entry) * 1.0 - size
                won = True
            else:
                pnl = -size
                won = False
        else:
            no_price = 1.0 - entry
            if actual == "NO_WON":
                pnl = (size / no_price) * 1.0 - size
                won = True
            else:
                pnl = -size
                won = False

        single_trades.append({
            "question": question[:80],
            "claude_prob": claude_prob,
            "direction": direction,
            "actual": actual,
            "won": won,
            "pnl": pnl,
            "edge": abs_edge,
            "confidence": confidence,
        })

    total = len(single_trades)
    wins = sum(1 for t in single_trades if t["won"])
    total_pnl = sum(t["pnl"] for t in single_trades)
    avg_pnl = total_pnl / total if total else 0

    print(f"\n{'='*60}")
    print(f"  REALISTIC SINGLE-TRADE ANALYSIS (entry=0.50)")
    print(f"{'='*60}")
    print(f"  Markets with signal: {total} / {len(markets)} ({total/len(markets)*100:.0f}%)")
    print(f"  Win rate:            {wins}/{total} = {wins/total*100:.1f}%")
    print(f"  Total P&L:           ${total_pnl:+.2f}")
    print(f"  Avg P&L/trade:       ${avg_pnl:+.4f}")

    # Direction breakdown
    yes_trades = [t for t in single_trades if t["direction"] == "buy_yes"]
    no_trades = [t for t in single_trades if t["direction"] == "buy_no"]
    yes_wins = sum(1 for t in yes_trades if t["won"])
    no_wins = sum(1 for t in no_trades if t["won"])
    print(f"\n  buy_yes: {len(yes_trades)} trades, {yes_wins}/{len(yes_trades)} wins = {yes_wins/len(yes_trades)*100:.1f}%")
    print(f"  buy_no:  {len(no_trades)} trades, {no_wins}/{len(no_trades)} wins = {no_wins/len(no_trades)*100:.1f}%")

    # Realistic ARR
    # Assume: bot finds and trades ~5 signals/day at $2 each
    print(f"\n  REALISTIC ARR ESTIMATES:")
    for trades_per_day in [3, 5, 8]:
        daily_gross = avg_pnl * trades_per_day
        monthly_gross = daily_gross * 30
        monthly_net = monthly_gross - 20
        annual_net = monthly_net * 12
        arr_pct = (annual_net / 75) * 100

        print(f"\n    At {trades_per_day} trades/day:")
        print(f"      Daily gross:   ${daily_gross:+.2f}")
        print(f"      Monthly net:   ${monthly_net:+.2f}")
        print(f"      Annual net:    ${annual_net:+.2f}")
        print(f"      ARR %:         {arr_pct:+.1f}%")

    # Calibration summary
    print(f"\n  CALIBRATION (key ranges):")
    cal = results["calibration"]
    for bucket, stats in cal.items():
        if stats["count"] > 0:
            expected_mid = (float(bucket.split("-")[0]) + float(bucket.split("-")[1])) / 2
            actual = stats["actual_rate"]
            error = actual - expected_mid
            print(f"    {bucket}: {stats['count']:3d} mkts, "
                  f"expected ~{expected_mid:.0%}, actual {actual:.1%}, "
                  f"error {error:+.1%}")

    # Overconfidence analysis
    print(f"\n  OVERCONFIDENCE ANALYSIS:")
    strong_yes = [t for t in single_trades if t["claude_prob"] >= 0.80]
    strong_no = [t for t in single_trades if t["claude_prob"] <= 0.20]
    mid = [t for t in single_trades if 0.40 <= t["claude_prob"] <= 0.60]

    if strong_yes:
        sy_wins = sum(1 for t in strong_yes if t["won"])
        print(f"    Claude >= 80% YES: {len(strong_yes)} trades, {sy_wins}/{len(strong_yes)} won ({sy_wins/len(strong_yes)*100:.0f}%)")
    if strong_no:
        sn_wins = sum(1 for t in strong_no if t["won"])
        print(f"    Claude <= 20% YES: {len(strong_no)} trades, {sn_wins}/{len(strong_no)} won ({sn_wins/len(strong_no)*100:.0f}%)")
    if mid:
        m_wins = sum(1 for t in mid if t["won"])
        print(f"    Claude 40-60% YES: {len(mid)} trades, {m_wins}/{len(mid)} won ({m_wins/len(mid)*100:.0f}%)")

    print(f"{'='*60}")


if __name__ == "__main__":
    analyze()
