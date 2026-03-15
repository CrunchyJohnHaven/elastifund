"""Monte Carlo portfolio simulation.

Simulates 10,000 portfolio paths over 12 months using empirical
trade outcome distribution from backtest data.
"""
from __future__ import annotations

import hashlib
import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_empirical_trades(entry_price=0.50, edge_threshold=0.05):
    """Load trade outcomes from backtest data with Kelly fractions."""
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    # Kelly fraction calculation (matches src/sizing.py)
    winner_fee = 0.02
    payout = 1.0 - winner_fee

    trades = []
    for m in markets:
        key = hashlib.sha256(m["question"].encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        prob = est["probability"]
        edge = prob - entry_price
        if abs(edge) < edge_threshold:
            continue

        direction = "buy_yes" if edge > 0 else "buy_no"
        actual = m["actual_outcome"]

        if direction == "buy_yes":
            won = actual == "YES_WON"
            pnl_pct = (payout / entry_price) - 1.0 if won else -1.0
            p_win = prob
            cost = entry_price
        else:
            no_price = 1.0 - entry_price
            won = actual == "NO_WON"
            pnl_pct = (payout / no_price) - 1.0 if won else -1.0
            p_win = 1.0 - prob
            cost = no_price

        # Compute Kelly fraction for this trade
        kelly_f = 0.0
        if 0 < cost < payout and 0 < p_win < 1:
            odds = (payout - cost) / cost
            if odds > 0:
                kelly_f = max(0, (p_win * odds - (1.0 - p_win)) / odds)

        # Base Kelly multiplier (asymmetric: NO gets 0.35x, YES gets 0.25x)
        base_mult = 0.35 if direction == "buy_no" else 0.25

        trades.append({
            "pnl_pct": pnl_pct,
            "won": won,
            "direction": direction,
            "kelly_f": kelly_f,
            "base_mult": base_mult,
        })

    return trades


def run_simulation(
    empirical_trades,
    starting_capital=75.0,
    trades_per_day=5,
    days=365,
    num_paths=10000,
    position_size=2.0,
    infra_cost_monthly=20.0,
    use_kelly=True,
    max_position=10.0,
    min_position=0.50,
):
    """Run Monte Carlo simulation.

    Args:
        use_kelly: If True, use quarter-Kelly sizing with bankroll scaling.
                   If False, use flat position_size.
        max_position: Kelly hard cap per position.
        min_position: Kelly floor per position.
    """
    total_trades = trades_per_day * days
    daily_infra = infra_cost_monthly / 30.0

    # Bankroll scaling tiers (matches src/sizing.py)
    bankroll_tiers = [(500.0, 0.75), (300.0, 0.50), (0.0, 0.25)]

    final_capitals = []
    max_drawdowns = []
    ruin_count = 0
    ruin_50pct_count = 0  # Hit 50% drawdown at any point
    double_3mo = 0
    double_6mo = 0
    double_12mo = 0
    monthly_returns = [[] for _ in range(12)]

    # Store some sample paths for charting
    sample_paths = []

    for path_idx in range(num_paths):
        capital = starting_capital
        peak = capital
        max_dd = 0.0
        daily_capitals = []

        for day in range(days):
            # Daily infrastructure cost
            capital -= daily_infra

            # Execute trades
            for _ in range(trades_per_day):
                if capital <= 0:
                    break

                trade = random.choice(empirical_trades)

                if use_kelly:
                    kelly_f = trade.get("kelly_f", 0)
                    if kelly_f <= 0:
                        continue
                    base_mult = trade.get("base_mult", 0.25)
                    # Bankroll scaling
                    bankroll_mult = bankroll_tiers[-1][1]
                    for threshold, mult in bankroll_tiers:
                        if capital >= threshold:
                            bankroll_mult = mult
                            break
                    effective_mult = max(base_mult, bankroll_mult) if capital >= 300 else base_mult
                    raw_size = kelly_f * effective_mult * capital
                    size = min(raw_size, max_position)
                    if size < min_position:
                        continue
                else:
                    size = min(position_size, capital)

                pnl = size * trade["pnl_pct"]
                capital += pnl

            capital = max(0, capital)
            daily_capitals.append(capital)

            # Track peak/drawdown
            peak = max(peak, capital)
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

            # Check milestones
            if day == 89:  # 3 months
                if capital >= starting_capital * 2:
                    double_3mo += 1
            elif day == 179:  # 6 months
                if capital >= starting_capital * 2:
                    double_6mo += 1

        # 12 month check
        if capital >= starting_capital * 2:
            double_12mo += 1

        if capital <= 0:
            ruin_count += 1

        if max_dd >= 0.50:
            ruin_50pct_count += 1

        final_capitals.append(capital)
        max_drawdowns.append(max_dd)

        # Monthly returns
        for month in range(12):
            start_day = month * 30
            end_day = min((month + 1) * 30, days) - 1
            if start_day < len(daily_capitals) and end_day < len(daily_capitals):
                start_val = daily_capitals[start_day] if start_day > 0 else starting_capital
                end_val = daily_capitals[end_day]
                if start_val > 0:
                    monthly_returns[month].append((end_val - start_val) / start_val)

        # Save first 20 paths for charting
        if path_idx < 20:
            sample_paths.append(daily_capitals)

    # Compute percentiles
    final_capitals.sort()
    max_drawdowns.sort()

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    avg_monthly_returns = []
    for month_data in monthly_returns:
        if month_data:
            avg_monthly_returns.append(sum(month_data) / len(month_data))

    results = {
        "parameters": {
            "starting_capital": starting_capital,
            "trades_per_day": trades_per_day,
            "days": days,
            "num_paths": num_paths,
            "position_size": position_size,
            "sizing_method": "quarter-kelly" if use_kelly else "flat",
            "infra_cost_monthly": infra_cost_monthly,
            "empirical_trades": len(empirical_trades),
            "empirical_win_rate": sum(1 for t in empirical_trades if t["won"]) / len(empirical_trades),
        },
        "final_capital": {
            "mean": sum(final_capitals) / len(final_capitals),
            "median": percentile(final_capitals, 50),
            "p5": percentile(final_capitals, 5),
            "p25": percentile(final_capitals, 25),
            "p75": percentile(final_capitals, 75),
            "p95": percentile(final_capitals, 95),
            "min": final_capitals[0],
            "max": final_capitals[-1],
        },
        "risk": {
            "probability_of_ruin": ruin_count / num_paths,
            "probability_50pct_drawdown": ruin_50pct_count / num_paths,
            "avg_max_drawdown": sum(max_drawdowns) / len(max_drawdowns),
            "median_max_drawdown": percentile(max_drawdowns, 50),
            "p95_max_drawdown": percentile(max_drawdowns, 95),
            "dd_ratio_p95_to_median": round(
                percentile(max_drawdowns, 95) / max(percentile(max_drawdowns, 50), 0.001), 2
            ),
        },
        "milestones": {
            "prob_double_3mo": double_3mo / num_paths,
            "prob_double_6mo": double_6mo / num_paths,
            "prob_double_12mo": double_12mo / num_paths,
        },
        "arr": {
            "median_arr": ((percentile(final_capitals, 50) - starting_capital) / starting_capital) * 100,
            "p5_arr": ((percentile(final_capitals, 5) - starting_capital) / starting_capital) * 100,
            "p95_arr": ((percentile(final_capitals, 95) - starting_capital) / starting_capital) * 100,
            "mean_arr": ((sum(final_capitals) / len(final_capitals) - starting_capital) / starting_capital) * 100,
        },
        "avg_monthly_returns_pct": [round(r * 100, 1) for r in avg_monthly_returns],
        "sample_paths": sample_paths[:5],  # 5 for compactness
    }

    return results


def print_simulation_report(results):
    """Print formatted simulation results."""
    p = results["parameters"]
    fc = results["final_capital"]
    risk = results["risk"]
    ms = results["milestones"]
    arr = results["arr"]

    print("\n" + "=" * 70)
    print("  MONTE CARLO PORTFOLIO SIMULATION")
    print("=" * 70)
    print(f"  Paths: {p['num_paths']:,} | Days: {p['days']} | Trades/day: {p['trades_per_day']}")
    print(f"  Starting capital: ${p['starting_capital']:.2f} | Position: ${p['position_size']:.2f}")
    print(f"  Infra cost: ${p['infra_cost_monthly']:.2f}/mo | Empirical win rate: {p['empirical_win_rate']:.1%}")

    print(f"\n  FINAL CAPITAL (after {p['days']} days):")
    print(f"    5th percentile:   ${fc['p5']:>10.2f}  (worst reasonable case)")
    print(f"    25th percentile:  ${fc['p25']:>10.2f}")
    print(f"    Median:           ${fc['median']:>10.2f}")
    print(f"    Mean:             ${fc['mean']:>10.2f}")
    print(f"    75th percentile:  ${fc['p75']:>10.2f}")
    print(f"    95th percentile:  ${fc['p95']:>10.2f}  (best reasonable case)")

    print(f"\n  ANNUALIZED RETURN:")
    print(f"    5th percentile:   {arr['p5_arr']:>+8.1f}%")
    print(f"    Median:           {arr['median_arr']:>+8.1f}%")
    print(f"    Mean:             {arr['mean_arr']:>+8.1f}%")
    print(f"    95th percentile:  {arr['p95_arr']:>+8.1f}%")

    print(f"\n  RISK METRICS:")
    print(f"    Probability of ruin:     {risk['probability_of_ruin']:.1%}")
    print(f"    P(50% drawdown):         {risk.get('probability_50pct_drawdown', 0):.1%}  (target < 5%)")
    print(f"    Avg max drawdown:        {risk['avg_max_drawdown']:.1%}")
    print(f"    Median max drawdown:     {risk['median_max_drawdown']:.1%}")
    print(f"    95th pct max drawdown:   {risk['p95_max_drawdown']:.1%}")
    print(f"    p95/median DD ratio:     {risk.get('dd_ratio_p95_to_median', 0):.1f}x  (expect 1.5-3x)")

    print(f"\n  MILESTONES:")
    print(f"    Prob double in 3 months:  {ms['prob_double_3mo']:.1%}")
    print(f"    Prob double in 6 months:  {ms['prob_double_6mo']:.1%}")
    print(f"    Prob double in 12 months: {ms['prob_double_12mo']:.1%}")

    if results.get("avg_monthly_returns_pct"):
        print(f"\n  AVG MONTHLY RETURNS:")
        for i, r in enumerate(results["avg_monthly_returns_pct"]):
            print(f"    Month {i+1}: {r:+.1f}%")

    print("=" * 70)


def run_multi_capital():
    """Run simulation at multiple capital levels with Kelly and flat sizing."""
    trades = load_empirical_trades()
    print(f"Loaded {len(trades)} empirical trade outcomes")
    print(f"Win rate: {sum(1 for t in trades if t['won'])/len(trades):.1%}")
    avg_kelly = sum(t.get('kelly_f', 0) for t in trades) / len(trades)
    print(f"Avg Kelly fraction: {avg_kelly:.4f}")

    for capital in [75, 1000, 10000]:
        # Flat sizing scales with capital
        if capital <= 100:
            pos_size = 2.0
        elif capital <= 5000:
            pos_size = 10.0
        else:
            pos_size = 50.0

        # Run flat sizing
        results_flat = run_simulation(
            trades,
            starting_capital=capital,
            trades_per_day=5,
            position_size=pos_size,
            use_kelly=False,
        )

        # Run Kelly sizing
        results_kelly = run_simulation(
            trades,
            starting_capital=capital,
            trades_per_day=5,
            use_kelly=True,
        )

        print(f"\n{'#' * 70}")
        print(f"  CAPITAL: ${capital:,.2f}")
        print(f"{'#' * 70}")
        print(f"\n  --- FLAT ${pos_size:.2f} ---")
        print_simulation_report(results_flat)
        print(f"\n  --- QUARTER-KELLY ---")
        print_simulation_report(results_kelly)

        # Compare
        kelly_median = results_kelly["final_capital"]["median"]
        flat_median = results_flat["final_capital"]["median"]
        advantage = ((kelly_median - flat_median) / flat_median * 100) if flat_median > 0 else 0
        print(f"\n  KELLY ADVANTAGE: {advantage:+.1f}% median final capital over flat")

    # Save the $75 Kelly simulation for the report
    results_75 = run_simulation(trades, starting_capital=75, trades_per_day=5, use_kelly=True)
    with open(os.path.join(DATA_DIR, "monte_carlo_results.json"), "w") as f:
        json.dump(results_75, f, indent=2, default=str)
    print(f"\nSaved $75 Kelly simulation to data/monte_carlo_results.json")


if __name__ == "__main__":
    run_multi_capital()
