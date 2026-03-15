#!/usr/bin/env python3
"""Backtest exit strategy: compare hold-to-resolution vs early exit.

Simulates pre-resolution exits on the historical market dataset.
Since we don't have intra-market price histories, we use a synthetic
price path model based on the known entry and final outcome.

Model:
  - Entry at simulated price (0.50)
  - Final price: 1.0 (YES won) or 0.0 (NO won)
  - Assume price follows a random walk from entry to final over N days
  - Apply exit rules each simulated day

This gives a realistic comparison of:
  1. Hold-to-resolution (current behavior)
  2. Early exit with profit targets, stop losses, time decay, momentum
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import dataclass

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RANDOM_SEED = 42


@dataclass
class ExitSimResult:
    question: str
    direction: str
    entry_price: float
    claude_prob: float
    actual_outcome: str
    exit_reason: str  # "resolution", "edge_captured", "stop_loss", "time_decay", "momentum"
    exit_price: float
    exit_day: int
    hold_days: int  # Total days market was open (for resolution)
    pnl: float
    won: bool
    capital_days: float  # position_size * hold_days (capital locked)


def generate_price_path(
    entry_price: float,
    final_price: float,
    total_days: int,
    volatility: float = 0.03,
    seed: int = 0,
) -> list[float]:
    """Generate a synthetic price path from entry to final.

    Uses a Brownian bridge: random walk that starts at entry_price
    and ends at final_price over total_days steps.
    """
    rng = random.Random(seed)
    if total_days <= 1:
        return [entry_price, final_price]

    path = [entry_price]
    for day in range(1, total_days + 1):
        t = day / total_days
        # Brownian bridge: expected value at time t
        expected = entry_price + (final_price - entry_price) * t
        # Add noise that diminishes as we approach resolution
        remaining_vol = volatility * math.sqrt(t * (1 - t)) if t < 1 else 0
        noise = rng.gauss(0, remaining_vol) if remaining_vol > 0 else 0
        price = max(0.01, min(0.99, expected + noise))
        path.append(price)

    # Ensure final price matches
    path[-1] = final_price
    return path


def simulate_exit_strategy(
    markets: list[dict],
    cache: dict,
    entry_price: float = 0.50,
    edge_threshold: float = 0.05,
    position_size: float = 2.0,
    # Exit params
    edge_capture_pct: float = 0.80,
    stop_loss_pct: float = 0.50,  # 50% of position value
    time_decay_days: int = 14,
    time_decay_movement: float = 0.05,
    momentum_cycles: int = 3,
    momentum_reduce_pct: float = 0.50,
    # Market assumptions
    avg_market_days: int = 14,
    price_volatility: float = 0.03,
) -> list[ExitSimResult]:
    """Simulate exit strategy on historical markets.

    Returns list of ExitSimResult for each simulated trade.
    """
    rng = random.Random(RANDOM_SEED)
    results: list[ExitSimResult] = []

    for idx, market in enumerate(markets):
        question = market["question"]
        actual = market["actual_outcome"]

        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        claude_prob = est["probability"]
        edge = claude_prob - entry_price

        if abs(edge) < edge_threshold:
            continue

        direction = "buy_yes" if edge > 0 else "buy_no"

        # Determine final YES price based on outcome
        final_yes_price = 1.0 if actual == "YES_WON" else 0.0

        # Randomize market duration (7-21 days)
        market_days = max(3, rng.randint(
            avg_market_days - 7,
            avg_market_days + 7,
        ))

        # Generate synthetic price path
        path = generate_price_path(
            entry_price=entry_price,
            final_price=final_yes_price,
            total_days=market_days,
            volatility=price_volatility,
            seed=RANDOM_SEED + idx,
        )

        # Simulate daily exit checks
        exit_reason = "resolution"
        exit_day = market_days
        exit_yes_price = final_yes_price
        adverse_cycles = 0
        last_check_price = entry_price
        remaining_size = position_size

        for day in range(1, market_days):
            current_yes_price = path[day]

            # --- EDGE CAPTURED ---
            if direction == "buy_yes":
                target = claude_prob
                edge_total = target - entry_price
                captured = current_yes_price - entry_price
                if edge_total > 0 and captured / edge_total >= edge_capture_pct:
                    exit_reason = "edge_captured"
                    exit_day = day
                    exit_yes_price = current_yes_price
                    break
            else:  # buy_no
                no_entry = 1.0 - entry_price
                no_current = 1.0 - current_yes_price
                no_target = 1.0 - claude_prob
                edge_total = no_target - no_entry
                captured = no_current - no_entry
                if edge_total > 0 and captured / edge_total >= edge_capture_pct:
                    exit_reason = "edge_captured"
                    exit_day = day
                    exit_yes_price = current_yes_price
                    break

            # --- STOP LOSS ---
            if direction == "buy_yes":
                loss = entry_price - current_yes_price
                if loss > stop_loss_pct * entry_price:
                    exit_reason = "stop_loss"
                    exit_day = day
                    exit_yes_price = current_yes_price
                    break
            else:
                # NO position loses when YES rises
                no_loss = current_yes_price - entry_price
                if no_loss > stop_loss_pct * (1.0 - entry_price):
                    exit_reason = "stop_loss"
                    exit_day = day
                    exit_yes_price = current_yes_price
                    break

            # --- TIME DECAY ---
            if day >= time_decay_days:
                movement = abs(current_yes_price - entry_price)
                if movement < time_decay_movement:
                    exit_reason = "time_decay"
                    exit_day = day
                    exit_yes_price = current_yes_price
                    break

            # --- MOMENTUM ---
            if direction == "buy_yes":
                if current_yes_price < last_check_price:
                    adverse_cycles += 1
                else:
                    adverse_cycles = 0
            else:
                if current_yes_price > last_check_price:
                    adverse_cycles += 1
                else:
                    adverse_cycles = 0

            if adverse_cycles >= momentum_cycles:
                exit_reason = "momentum"
                exit_day = day
                exit_yes_price = current_yes_price
                remaining_size *= (1.0 - momentum_reduce_pct)
                adverse_cycles = 0
                # Don't break — momentum is partial, continue monitoring
                # But for simplicity in backtest, we exit fully
                break

            last_check_price = current_yes_price

        # Calculate P&L
        if direction == "buy_yes":
            if exit_reason == "resolution":
                won = actual == "YES_WON"
                pnl = (remaining_size / entry_price) - remaining_size if won else -remaining_size
            else:
                # Early exit at exit_yes_price
                pnl = remaining_size * (exit_yes_price - entry_price) / entry_price
                won = pnl > 0
        else:  # buy_no
            no_entry = 1.0 - entry_price
            if exit_reason == "resolution":
                won = actual == "NO_WON"
                pnl = (remaining_size / no_entry) - remaining_size if won else -remaining_size
            else:
                no_exit = 1.0 - exit_yes_price
                pnl = remaining_size * (no_exit - no_entry) / no_entry
                won = pnl > 0

        results.append(ExitSimResult(
            question=question[:80],
            direction=direction,
            entry_price=entry_price,
            claude_prob=claude_prob,
            actual_outcome=actual,
            exit_reason=exit_reason,
            exit_price=exit_yes_price,
            exit_day=exit_day,
            hold_days=market_days,
            pnl=round(pnl, 4),
            won=won,
            capital_days=round(remaining_size * exit_day, 2),
        ))

    return results


def compare_strategies(results_hold: list[ExitSimResult], results_exit: list[ExitSimResult]) -> dict:
    """Compare hold-to-resolution vs early exit strategy."""

    def summarize(trades: list[ExitSimResult], label: str) -> dict:
        n = len(trades)
        if n == 0:
            return {"label": label, "trades": 0}
        wins = sum(1 for t in trades if t.won)
        total_pnl = sum(t.pnl for t in trades)
        avg_pnl = total_pnl / n
        avg_hold = sum(t.exit_day for t in trades) / n
        total_capital_days = sum(t.capital_days for t in trades)

        # Capital velocity: lower capital-days per unit of P&L = better
        capital_efficiency = total_pnl / total_capital_days if total_capital_days > 0 else 0

        # Drawdown
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cum += t.pnl
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        # ARR estimate (5 trades/day, $75 capital, $20/mo infra)
        daily_gross = avg_pnl * 5
        monthly_net = daily_gross * 30 - 20
        arr_pct = (monthly_net * 12 / 75.0) * 100

        return {
            "label": label,
            "trades": n,
            "wins": wins,
            "win_rate": round(wins / n, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 4),
            "avg_hold_days": round(avg_hold, 1),
            "total_capital_days": round(total_capital_days, 1),
            "capital_efficiency": round(capital_efficiency, 6),
            "max_drawdown": round(max_dd, 2),
            "arr_pct": round(arr_pct, 1),
        }

    hold_summary = summarize(results_hold, "Hold to Resolution")
    exit_summary = summarize(results_exit, "Early Exit Strategy")

    # Exit reason breakdown
    exit_reasons = {}
    for t in results_exit:
        r = t.exit_reason
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "wins": 0, "total_pnl": 0.0, "avg_hold": 0.0}
        exit_reasons[r]["count"] += 1
        if t.won:
            exit_reasons[r]["wins"] += 1
        exit_reasons[r]["total_pnl"] += t.pnl

    for r, stats in exit_reasons.items():
        n = stats["count"]
        exits_of_type = [t for t in results_exit if t.exit_reason == r]
        stats["win_rate"] = round(stats["wins"] / n, 4) if n > 0 else 0
        stats["avg_pnl"] = round(stats["total_pnl"] / n, 4) if n > 0 else 0
        stats["total_pnl"] = round(stats["total_pnl"], 2)
        stats["avg_hold"] = round(sum(t.exit_day for t in exits_of_type) / n, 1) if n > 0 else 0

    # Capital velocity improvement
    hold_cap_days = hold_summary.get("total_capital_days", 1)
    exit_cap_days = exit_summary.get("total_capital_days", 1)
    velocity_improvement = (hold_cap_days / exit_cap_days) if exit_cap_days > 0 else 1.0

    return {
        "hold_to_resolution": hold_summary,
        "early_exit": exit_summary,
        "exit_reasons": exit_reasons,
        "improvement": {
            "pnl_delta": round(exit_summary["total_pnl"] - hold_summary["total_pnl"], 2),
            "win_rate_delta": round(exit_summary["win_rate"] - hold_summary["win_rate"], 4),
            "avg_hold_reduction_days": round(hold_summary["avg_hold_days"] - exit_summary["avg_hold_days"], 1),
            "capital_velocity_multiplier": round(velocity_improvement, 2),
            "arr_delta": round(exit_summary["arr_pct"] - hold_summary["arr_pct"], 1),
        },
    }


def run_exit_backtest():
    """Main entry point: run exit strategy backtest and compare."""
    # Load data
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    print(f"Loaded {len(markets)} markets, {len(cache)} cached estimates")

    # Hold-to-resolution baseline (no exit rules)
    print("\nSimulating hold-to-resolution baseline...")
    results_hold = simulate_exit_strategy(
        markets, cache,
        edge_capture_pct=99.0,  # Never triggers
        stop_loss_pct=99.0,     # Never triggers
        time_decay_days=9999,   # Never triggers
        momentum_cycles=9999,   # Never triggers
    )

    # Early exit strategy
    print("Simulating early exit strategy...")
    results_exit = simulate_exit_strategy(
        markets, cache,
        edge_capture_pct=0.80,
        stop_loss_pct=0.50,
        time_decay_days=14,
        time_decay_movement=0.05,
        momentum_cycles=3,
    )

    # Compare
    comparison = compare_strategies(results_hold, results_exit)

    # Print report
    print_exit_report(comparison)

    # Save
    out_path = os.path.join(DATA_DIR, "exit_backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"\nSaved to {out_path}")

    return comparison


def print_exit_report(comparison: dict):
    """Print formatted exit strategy comparison."""
    hold = comparison["hold_to_resolution"]
    exit_ = comparison["early_exit"]
    imp = comparison["improvement"]

    print("\n" + "=" * 70)
    print("  EXIT STRATEGY BACKTEST COMPARISON")
    print("=" * 70)

    print(f"\n  {'Metric':<30s} {'Hold-to-Res':>15s} {'Early Exit':>15s} {'Delta':>10s}")
    print(f"  {'-'*70}")
    print(f"  {'Trades':<30s} {hold['trades']:>15d} {exit_['trades']:>15d}")
    print(f"  {'Win Rate':<30s} {hold['win_rate']:>14.1%} {exit_['win_rate']:>14.1%} {imp['win_rate_delta']:>+9.1%}")
    print(f"  {'Total P&L':<30s} ${hold['total_pnl']:>13.2f} ${exit_['total_pnl']:>13.2f} ${imp['pnl_delta']:>+8.2f}")
    print(f"  {'Avg P&L/trade':<30s} ${hold['avg_pnl']:>13.4f} ${exit_['avg_pnl']:>13.4f}")
    print(f"  {'Avg Hold (days)':<30s} {hold['avg_hold_days']:>14.1f} {exit_['avg_hold_days']:>14.1f} {imp['avg_hold_reduction_days']:>+9.1f}")
    print(f"  {'Capital-Days':<30s} {hold['total_capital_days']:>14.1f} {exit_['total_capital_days']:>14.1f}")
    print(f"  {'Capital Efficiency':<30s} {hold['capital_efficiency']:>14.6f} {exit_['capital_efficiency']:>14.6f}")
    print(f"  {'Max Drawdown':<30s} ${hold['max_drawdown']:>13.2f} ${exit_['max_drawdown']:>13.2f}")
    print(f"  {'ARR %':<30s} {hold['arr_pct']:>+13.1f}% {exit_['arr_pct']:>+13.1f}% {imp['arr_delta']:>+8.1f}%")

    print(f"\n  Capital Velocity Multiplier: {imp['capital_velocity_multiplier']:.2f}x")

    print(f"\n  EXIT REASON BREAKDOWN:")
    print(f"  {'Reason':<20s} {'Count':>6s} {'WinRate':>8s} {'AvgPnL':>10s} {'TotalPnL':>10s} {'AvgHold':>8s}")
    print(f"  {'-'*62}")
    for reason, stats in sorted(comparison["exit_reasons"].items()):
        print(f"  {reason:<20s} {stats['count']:>6d} {stats['win_rate']:>7.1%} "
              f"${stats['avg_pnl']:>+8.4f} ${stats['total_pnl']:>+8.2f} {stats['avg_hold']:>7.1f}d")

    print("=" * 70)


if __name__ == "__main__":
    run_exit_backtest()
