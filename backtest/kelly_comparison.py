"""Backtest comparison: Quarter-Kelly sizing vs flat $2 with compounding.

Runs sequential trades through the 532-market backtest data, simulating
bankroll compounding to compare Kelly vs flat sizing.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Add parent dir so we can import src.sizing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "polymarket-bot"))

from src.sizing import kelly_fraction, position_size, WINNER_FEE

STARTING_CAPITAL = 75.0
ENTRY_PRICE = 0.50  # Simulated entry price
EDGE_THRESHOLD = 0.05
FLAT_SIZE = 2.0


def load_trades():
    """Load markets + Claude estimates, generate trade list."""
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    trades = []
    for m in markets:
        key = hashlib.sha256(m["question"].encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        prob = est["probability"]
        edge = prob - ENTRY_PRICE
        if abs(edge) < EDGE_THRESHOLD:
            continue

        direction = "buy_yes" if edge > 0 else "buy_no"
        actual = m["actual_outcome"]

        trades.append({
            "question": m["question"][:80],
            "prob": prob,
            "direction": direction,
            "actual": actual,
            "category": m.get("category", "Unknown"),
        })

    return trades


def resolve_trade(direction: str, entry_price: float, size: float, actual: str) -> tuple[bool, float]:
    """Resolve a trade. Returns (won, pnl)."""
    payout = 1.0 - WINNER_FEE

    if direction == "buy_yes":
        if actual == "YES_WON":
            shares = size / entry_price
            return True, shares * payout - size
        else:
            return False, -size
    else:  # buy_no
        no_price = 1.0 - entry_price
        if actual == "NO_WON":
            shares = size / no_price
            return True, shares * payout - size
        else:
            return False, -size


def run_flat(trades: list[dict]) -> dict:
    """Run flat $2 sizing with compounding bankroll."""
    bankroll = STARTING_CAPITAL
    peak = bankroll
    max_drawdown = 0.0
    trade_count = 0
    wins = 0
    pnl_series = []
    bankroll_series = [bankroll]

    for t in trades:
        size = min(FLAT_SIZE, bankroll)
        if size < 0.50 or bankroll <= 0:
            continue

        won, pnl = resolve_trade(t["direction"], ENTRY_PRICE, size, t["actual"])
        bankroll += pnl
        bankroll = max(0, bankroll)
        trade_count += 1
        if won:
            wins += 1
        pnl_series.append(pnl)
        bankroll_series.append(bankroll)

        peak = max(peak, bankroll)
        dd = (peak - bankroll) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    returns = [p / FLAT_SIZE for p in pnl_series] if pnl_series else [0]
    sharpe = (statistics.mean(returns) / statistics.stdev(returns) if len(returns) > 1 and statistics.stdev(returns) > 0 else 0)

    return {
        "strategy": "Flat $2.00",
        "final_bankroll": round(bankroll, 2),
        "total_return_pct": round((bankroll - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 1),
        "trade_count": trade_count,
        "win_rate": round(wins / trade_count * 100, 1) if trade_count else 0,
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "sharpe": round(sharpe, 3),
        "total_pnl": round(sum(pnl_series), 2),
    }


def run_kelly(trades: list[dict]) -> dict:
    """Run quarter-Kelly sizing with compounding bankroll."""
    bankroll = STARTING_CAPITAL
    peak = bankroll
    max_drawdown = 0.0
    trade_count = 0
    wins = 0
    pnl_series = []
    sizes = []
    kelly_fs = []
    bankroll_series = [bankroll]
    category_counts: dict[str, int] = {}

    for t in trades:
        if bankroll <= 0:
            break

        k_f = kelly_fraction(t["prob"], ENTRY_PRICE, t["direction"])
        if k_f <= 0:
            continue

        cat = t.get("category", "Unknown")
        size = position_size(
            bankroll=bankroll,
            kelly_f=k_f,
            side=t["direction"],
            category=cat,
            category_counts=category_counts,
            max_position_override=10.0,
        )
        if size <= 0:
            continue

        won, pnl = resolve_trade(t["direction"], ENTRY_PRICE, size, t["actual"])
        bankroll += pnl
        bankroll = max(0, bankroll)
        trade_count += 1
        if won:
            wins += 1
        pnl_series.append(pnl)
        sizes.append(size)
        kelly_fs.append(k_f)
        bankroll_series.append(bankroll)

        # Track category counts (simplified — in live mode these close)
        category_counts[cat] = category_counts.get(cat, 0) + 1

        peak = max(peak, bankroll)
        dd = (peak - bankroll) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    returns = [pnl_series[i] / sizes[i] for i in range(len(pnl_series)) if sizes[i] > 0] if pnl_series else [0]
    sharpe = (statistics.mean(returns) / statistics.stdev(returns) if len(returns) > 1 and statistics.stdev(returns) > 0 else 0)

    return {
        "strategy": "Quarter-Kelly",
        "final_bankroll": round(bankroll, 2),
        "total_return_pct": round((bankroll - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 1),
        "trade_count": trade_count,
        "win_rate": round(wins / trade_count * 100, 1) if trade_count else 0,
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "sharpe": round(sharpe, 3),
        "total_pnl": round(sum(pnl_series), 2),
        "avg_size": round(statistics.mean(sizes), 2) if sizes else 0,
        "avg_kelly_f": round(statistics.mean(kelly_fs), 4) if kelly_fs else 0,
    }


def main():
    trades = load_trades()
    print(f"Loaded {len(trades)} trades from backtest data")
    print(f"Starting capital: ${STARTING_CAPITAL:.2f}")
    print(f"Entry price: {ENTRY_PRICE}")
    print()

    flat_results = run_flat(trades)
    kelly_results = run_kelly(trades)

    print("=" * 70)
    print("  BACKTEST COMPARISON: Kelly vs Flat Sizing (Compounding)")
    print("=" * 70)

    headers = ["Metric", "Flat $2.00", "Quarter-Kelly"]
    rows = [
        ("Final Bankroll", f"${flat_results['final_bankroll']:.2f}", f"${kelly_results['final_bankroll']:.2f}"),
        ("Total Return", f"{flat_results['total_return_pct']:.1f}%", f"{kelly_results['total_return_pct']:.1f}%"),
        ("Trade Count", str(flat_results['trade_count']), str(kelly_results['trade_count'])),
        ("Win Rate", f"{flat_results['win_rate']:.1f}%", f"{kelly_results['win_rate']:.1f}%"),
        ("Max Drawdown", f"{flat_results['max_drawdown_pct']:.1f}%", f"{kelly_results['max_drawdown_pct']:.1f}%"),
        ("Sharpe Ratio", f"{flat_results['sharpe']:.3f}", f"{kelly_results['sharpe']:.3f}"),
        ("Total P&L", f"${flat_results['total_pnl']:.2f}", f"${kelly_results['total_pnl']:.2f}"),
    ]
    if kelly_results.get("avg_size"):
        rows.append(("Avg Position Size", "$2.00", f"${kelly_results['avg_size']:.2f}"))
    if kelly_results.get("avg_kelly_f"):
        rows.append(("Avg Kelly Fraction", "N/A", f"{kelly_results['avg_kelly_f']:.4f}"))

    # Print table
    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(f"  {header_line}")
    print(f"  {'─' * len(header_line)}")
    for row in rows:
        line = "  ".join(row[i].ljust(col_widths[i]) for i in range(len(headers)))
        print(f"  {line}")

    # Kelly outperformance
    if flat_results['final_bankroll'] > 0:
        kelly_advantage = (kelly_results['final_bankroll'] - flat_results['final_bankroll']) / flat_results['final_bankroll'] * 100
        print(f"\n  Kelly outperformance: {kelly_advantage:+.1f}% over flat sizing")
        if kelly_advantage > 50:
            print("  STATUS: PASS — Kelly outperforms flat $2 by >50% on compounded returns")
        else:
            print(f"  STATUS: {'PASS' if kelly_advantage > 0 else 'FAIL'} — Kelly {'outperforms' if kelly_advantage > 0 else 'underperforms'} flat by {abs(kelly_advantage):.1f}%")

    print("=" * 70)

    # Save results
    comparison = {
        "flat": flat_results,
        "kelly": kelly_results,
        "starting_capital": STARTING_CAPITAL,
        "entry_price": ENTRY_PRICE,
        "edge_threshold": EDGE_THRESHOLD,
        "total_markets": len(trades),
    }
    output_path = os.path.join(DATA_DIR, "kelly_comparison.json")
    with open(output_path, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
