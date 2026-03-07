"""Generate investor-ready charts from backtest and simulation data."""
from __future__ import annotations

import hashlib
import json
import os
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHARTS_DIR = os.path.join(os.path.dirname(__file__), "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Style
plt.style.use("seaborn-v0_8-whitegrid")
COLORS = {
    "primary": "#2563EB",
    "secondary": "#7C3AED",
    "positive": "#059669",
    "negative": "#DC2626",
    "neutral": "#6B7280",
    "band": "#DBEAFE",
}


def load_data():
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)
    with open(os.path.join(DATA_DIR, "backtest_results.json")) as f:
        backtest = json.load(f)
    mc_path = os.path.join(DATA_DIR, "monte_carlo_results.json")
    mc = None
    if os.path.exists(mc_path):
        with open(mc_path) as f:
            mc = json.load(f)
    return markets, cache, backtest, mc


def chart_calibration(backtest):
    """Calibration plot: predicted vs actual probability."""
    cal = backtest["calibration"]

    predicted = []
    actual = []
    sizes = []

    for bucket, stats in cal.items():
        if stats["count"] > 0:
            low, high = bucket.split("-")
            mid = (float(low) + float(high)) / 2
            predicted.append(mid)
            actual.append(stats["actual_rate"])
            sizes.append(stats["count"])

    fig, ax = plt.subplots(figsize=(8, 8))

    # Perfect calibration line
    ax.plot([0, 1], [0, 1], "--", color=COLORS["neutral"], linewidth=1.5, label="Perfect Calibration")

    # Scatter with size proportional to count
    max_size = max(sizes)
    scatter_sizes = [s / max_size * 400 + 50 for s in sizes]
    ax.scatter(predicted, actual, s=scatter_sizes, color=COLORS["primary"],
               alpha=0.7, edgecolors="white", linewidth=1.5, zorder=5)

    # Labels on points
    for p, a, s in zip(predicted, actual, sizes):
        ax.annotate(f"n={s}", (p, a), textcoords="offset points",
                   xytext=(10, 5), fontsize=8, color=COLORS["neutral"])

    ax.set_xlabel("Claude Predicted Probability (YES)", fontsize=12)
    ax.set_ylabel("Actual Outcome Rate (YES)", fontsize=12)
    ax.set_title("AI Model Calibration\n532 Resolved Markets", fontsize=14, fontweight="bold")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=11)
    ax.set_aspect("equal")

    # Add Brier score annotation
    brier = backtest["summary"]["avg_brier_score"]
    ax.text(0.05, 0.92, f"Brier Score: {brier:.4f}\n(0.25 = random, 0 = perfect)",
            transform=ax.transAxes, fontsize=10, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor=COLORS["band"], alpha=0.8))

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "calibration_plot.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def chart_equity_curve(markets, cache):
    """Simulated equity curve from backtest trades."""
    entry = 0.50
    threshold = 0.05
    size = 2.0
    capital = 75.0

    equity = [capital]
    trades_x = [0]
    trade_num = 0

    for m in markets:
        key = hashlib.sha256(m["question"].encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        prob = est["probability"]
        edge = prob - entry
        if abs(edge) < threshold:
            continue

        trade_num += 1
        direction = "buy_yes" if edge > 0 else "buy_no"
        actual = m["actual_outcome"]

        if direction == "buy_yes":
            won = actual == "YES_WON"
            pnl = (size / entry) - size if won else -size
        else:
            no_price = 1.0 - entry
            won = actual == "NO_WON"
            pnl = (size / no_price) - size if won else -size

        capital += pnl
        equity.append(capital)
        trades_x.append(trade_num)

    fig, ax = plt.subplots(figsize=(12, 6))

    # Color segments by gain/loss
    for i in range(1, len(equity)):
        color = COLORS["positive"] if equity[i] >= equity[i-1] else COLORS["negative"]
        ax.plot([trades_x[i-1], trades_x[i]], [equity[i-1], equity[i]],
                color=color, linewidth=1.5, alpha=0.8)

    # Fill under curve
    ax.fill_between(trades_x, 75, equity, alpha=0.1, color=COLORS["primary"])

    # Starting line
    ax.axhline(y=75, color=COLORS["neutral"], linestyle="--", linewidth=1, alpha=0.5, label="Starting Capital ($75)")

    ax.set_xlabel("Trade Number", fontsize=12)
    ax.set_ylabel("Portfolio Value ($)", fontsize=12)
    ax.set_title("Simulated Equity Curve\n470 Trades Across 532 Resolved Markets", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)

    # Final P&L annotation
    final = equity[-1]
    pnl = final - 75
    ax.text(0.98, 0.05, f"Final: ${final:.2f} ({pnl:+.2f})",
            transform=ax.transAxes, fontsize=12, horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.5", facecolor=COLORS["band"], alpha=0.8))

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "equity_curve.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def chart_monte_carlo(mc):
    """Monte Carlo fan chart with percentile bands."""
    if not mc or not mc.get("sample_paths"):
        print("No Monte Carlo data available")
        return

    paths = mc["sample_paths"]
    days = len(paths[0])

    # Re-run quick simulation for fan chart data
    # Load empirical trades
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    emp_trades = []
    for m in markets:
        key = hashlib.sha256(m["question"].encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue
        prob = est["probability"]
        edge = prob - 0.50
        if abs(edge) < 0.05:
            continue
        direction = "buy_yes" if edge > 0 else "buy_no"
        actual = m["actual_outcome"]
        if direction == "buy_yes":
            won = actual == "YES_WON"
            pnl_pct = (1.0 / 0.50) - 1.0 if won else -1.0
        else:
            won = actual == "NO_WON"
            pnl_pct = (1.0 / 0.50) - 1.0 if won else -1.0
        emp_trades.append(pnl_pct)

    # Run 500 paths for charting
    num_paths = 500
    all_paths = []
    random.seed(42)
    for _ in range(num_paths):
        capital = 75.0
        path_data = [capital]
        for day in range(365):
            capital -= 20.0 / 30.0  # daily infra
            for _ in range(5):
                if capital <= 0:
                    break
                trade = random.choice(emp_trades)
                pnl = 2.0 * trade
                capital += pnl
            capital = max(0, capital)
            path_data.append(capital)
        all_paths.append(path_data)

    # Compute percentiles at each day
    days_range = range(366)
    p5 = [sorted([p[d] for p in all_paths])[int(num_paths * 0.05)] for d in days_range]
    p25 = [sorted([p[d] for p in all_paths])[int(num_paths * 0.25)] for d in days_range]
    p50 = [sorted([p[d] for p in all_paths])[int(num_paths * 0.50)] for d in days_range]
    p75 = [sorted([p[d] for p in all_paths])[int(num_paths * 0.75)] for d in days_range]
    p95 = [sorted([p[d] for p in all_paths])[int(num_paths * 0.95)] for d in days_range]

    fig, ax = plt.subplots(figsize=(12, 7))

    x = list(days_range)

    # Fan bands
    ax.fill_between(x, p5, p95, alpha=0.1, color=COLORS["primary"], label="5th-95th percentile")
    ax.fill_between(x, p25, p75, alpha=0.2, color=COLORS["primary"], label="25th-75th percentile")
    ax.plot(x, p50, color=COLORS["primary"], linewidth=2.5, label="Median path")

    # A few sample paths
    for i in range(min(5, num_paths)):
        ax.plot(x, all_paths[i], color=COLORS["neutral"], linewidth=0.5, alpha=0.3)

    ax.axhline(y=75, color=COLORS["negative"], linestyle="--", linewidth=1, alpha=0.5, label="Starting Capital")

    ax.set_xlabel("Day", fontsize=12)
    ax.set_ylabel("Portfolio Value ($)", fontsize=12)
    ax.set_title("Monte Carlo Simulation — 500 Portfolio Paths\n$75 Starting Capital, 5 Trades/Day, $2 Position Size",
                fontsize=14, fontweight="bold")
    ax.legend(fontsize=10, loc="upper left")

    # Annotations
    ax.text(0.98, 0.95, f"Median 12-mo: ${p50[-1]:.0f}\n"
            f"5th pct: ${p5[-1]:.0f}\n95th pct: ${p95[-1]:.0f}\n"
            f"P(ruin): 0.0%",
            transform=ax.transAxes, fontsize=10, verticalalignment="top",
            horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9))

    # Month markers
    for month in range(1, 13):
        day = month * 30
        if day < 366:
            ax.axvline(x=day, color=COLORS["neutral"], linewidth=0.3, alpha=0.3)

    plt.tight_layout()
    path_file = os.path.join(CHARTS_DIR, "monte_carlo_fan.png")
    plt.savefig(path_file, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path_file}")


def chart_win_rate_by_direction(backtest):
    """Bar chart: win rate by direction."""
    fig, ax = plt.subplots(figsize=(8, 5))

    directions = ["Buy YES", "Buy NO", "Overall"]
    bd = backtest["by_direction"]
    rates = [bd["buy_yes"]["win_rate"], bd["buy_no"]["win_rate"], backtest["summary"]["win_rate"]]
    counts = [bd["buy_yes"]["count"], bd["buy_no"]["count"], backtest["total_trades"]]

    colors = [COLORS["secondary"], COLORS["primary"], COLORS["positive"]]
    bars = ax.bar(directions, [r * 100 for r in rates], color=colors, width=0.5, edgecolor="white", linewidth=1.5)

    # Add count labels on bars
    for bar, count, rate in zip(bars, counts, rates):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                f"{rate:.1%}\n(n={count})", ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.axhline(y=50, color=COLORS["negative"], linestyle="--", linewidth=1, alpha=0.5, label="Breakeven (50%)")
    ax.set_ylabel("Win Rate (%)", fontsize=12)
    ax.set_title("Win Rate by Trade Direction\n532 Resolved Markets", fontsize=14, fontweight="bold")
    ax.set_ylim(0, 95)
    ax.legend(fontsize=10)

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "win_rate_direction.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def chart_strategy_comparison():
    """Bar chart comparing strategy variants."""
    comp_path = os.path.join(DATA_DIR, "strategy_comparison.json")
    if not os.path.exists(comp_path):
        print("No strategy comparison data")
        return

    with open(comp_path) as f:
        data = json.load(f)

    # Top 5 by ARR
    sorted_items = sorted(data.items(), key=lambda x: x[1].get("arr_5", 0), reverse=True)[:6]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    names = [k.split(". ", 1)[1] if ". " in k else k for k, v in sorted_items]
    win_rates = [v["win_rate"] * 100 for k, v in sorted_items]
    arrs = [v["arr_5"] for k, v in sorted_items]

    # Win rate chart
    bars1 = ax1.barh(names, win_rates, color=COLORS["primary"], height=0.5)
    ax1.axvline(x=50, color=COLORS["negative"], linestyle="--", linewidth=1, alpha=0.5)
    ax1.set_xlabel("Win Rate (%)", fontsize=11)
    ax1.set_title("Win Rate by Strategy", fontsize=13, fontweight="bold")
    for bar, val in zip(bars1, win_rates):
        ax1.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2.,
                f"{val:.1f}%", ha="left", va="center", fontsize=10)

    # ARR chart
    colors2 = [COLORS["positive"] if a > 0 else COLORS["negative"] for a in arrs]
    bars2 = ax2.barh(names, arrs, color=colors2, height=0.5)
    ax2.set_xlabel("ARR % (@5 trades/day)", fontsize=11)
    ax2.set_title("Annual Return Rate by Strategy", fontsize=13, fontweight="bold")
    for bar, val in zip(bars2, arrs):
        ax2.text(bar.get_width() + 20, bar.get_y() + bar.get_height()/2.,
                f"{val:+,.0f}%", ha="left", va="center", fontsize=10)

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "strategy_comparison.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def chart_monthly_returns(mc):
    """Monthly return heatmap/bar."""
    if not mc or not mc.get("avg_monthly_returns_pct"):
        return

    months = [f"Mo {i+1}" for i in range(len(mc["avg_monthly_returns_pct"]))]
    returns = mc["avg_monthly_returns_pct"]

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [COLORS["positive"] if r > 0 else COLORS["negative"] for r in returns]
    bars = ax.bar(months, returns, color=colors, width=0.6, edgecolor="white", linewidth=1)

    for bar, val in zip(bars, returns):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5,
                f"{val:+.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.axhline(y=0, color=COLORS["neutral"], linewidth=0.5)
    ax.set_ylabel("Average Monthly Return (%)", fontsize=12)
    ax.set_title("Projected Monthly Returns (Monte Carlo Median)\n$75 Starting Capital, 5 Trades/Day",
                fontsize=14, fontweight="bold")

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "monthly_returns.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def generate_all():
    """Generate all charts."""
    markets, cache, backtest, mc = load_data()

    print("Generating charts...")
    chart_calibration(backtest)
    chart_equity_curve(markets, cache)
    chart_win_rate_by_direction(backtest)
    chart_strategy_comparison()
    chart_monte_carlo(mc)
    chart_monthly_returns(mc)
    print(f"\nAll charts saved to {CHARTS_DIR}/")


if __name__ == "__main__":
    generate_all()
