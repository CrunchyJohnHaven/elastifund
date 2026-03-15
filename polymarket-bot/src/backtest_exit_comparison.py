"""Backtest comparison: Hold-to-Resolution vs Active Exit Strategy.

Simulates 532 markets (matching the historical dataset size) with synthetic
price paths. Compares two approaches:

1. HOLD: Buy and hold until resolution (market settles at 0 or 1)
2. ACTIVE EXIT: Same entries, but exit early when edge is captured/lost

Key metrics compared:
  - Total P&L
  - Capital velocity (annualized return per dollar-day deployed)
  - Average hold time
  - Max drawdown
  - Win rate

Usage:
    python -m src.backtest_exit_comparison
"""
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Simulation parameters ──────────────────────────────────────────────
NUM_MARKETS = 532
INITIAL_BANKROLL = 1000.0
POSITION_SIZE_USD = 5.0    # Fixed $5 per trade for simplicity
DAYS_PER_MARKET = 30       # Max days we simulate price evolution per market
WINNER_FEE = 0.02          # 2% winner fee

# Exit strategy thresholds (match ExitStrategyConfig defaults)
EDGE_CAPTURE_PCT = 0.80
STOP_LOSS_PCT = 0.15
TIME_DECAY_DAYS = 14
TIME_DECAY_MOVEMENT = 0.05

random.seed(42)


@dataclass
class TradeResult:
    """Result of a single simulated trade."""
    market_id: int
    side: str                  # "buy_yes" or "buy_no"
    entry_price: float
    exit_price: float
    resolution: Optional[float]  # 0.0 or 1.0 for hold strategy
    estimated_prob: float
    hold_days: float
    pnl: float
    exit_reason: str           # "resolution", "edge_captured", "stop_loss", "time_decay"
    capital_deployed: float


@dataclass
class StrategyResult:
    """Aggregate results for a strategy."""
    name: str
    trades: list[TradeResult] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def avg_hold_days(self) -> float:
        return statistics.mean(t.hold_days for t in self.trades) if self.trades else 0

    @property
    def total_dollar_days(self) -> float:
        """Total capital × time deployed (lower = more capital-efficient)."""
        return sum(t.capital_deployed * t.hold_days for t in self.trades)

    @property
    def capital_velocity(self) -> float:
        """Annualized return per dollar-day deployed."""
        if self.total_dollar_days <= 0:
            return 0
        return (self.total_pnl / self.total_dollar_days) * 365

    @property
    def win_rate(self) -> float:
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return (wins / len(self.trades) * 100) if self.trades else 0

    @property
    def max_drawdown(self) -> float:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_pnl_per_trade(self) -> float:
        return self.total_pnl / len(self.trades) if self.trades else 0

    @property
    def trades_possible_with_capital(self) -> int:
        """How many trades can we run with a fixed bankroll if capital recycles."""
        if self.avg_hold_days <= 0:
            return len(self.trades)
        slots = INITIAL_BANKROLL / POSITION_SIZE_USD
        cycles = DAYS_PER_MARKET / self.avg_hold_days
        return int(slots * cycles)


def generate_market_scenario() -> dict:
    """Generate a random market scenario.

    Returns dict with:
      - true_prob: actual probability the event happens
      - market_price: current YES price (what the market thinks)
      - our_estimate: our probability estimate
      - side: "buy_yes" or "buy_no"
      - resolution: 0.0 or 1.0 (actual outcome)
      - days_to_resolve: how long until resolution
      - daily_prices: list of daily YES prices until resolution
    """
    # True probability (unknown to us, used for simulation)
    true_prob = random.uniform(0.05, 0.95)

    # Market price: noisy estimate of true prob
    noise = random.gauss(0, 0.10)
    market_price = max(0.05, min(0.95, true_prob + noise))

    # Our estimate: somewhat better than market (simulating an edge)
    our_noise = random.gauss(0, 0.08)
    our_estimate = max(0.05, min(0.95, true_prob + our_noise))

    # Decide side based on our estimate vs market
    if our_estimate - market_price > 0.05:
        side = "buy_yes"
    elif market_price - our_estimate > 0.05:
        side = "buy_no"
    else:
        side = "hold"  # No edge

    # Resolution: based on true probability
    resolution = 1.0 if random.random() < true_prob else 0.0

    # Days to resolution
    days_to_resolve = random.randint(1, DAYS_PER_MARKET)

    # Generate daily price path (random walk toward resolution)
    daily_prices = _generate_price_path(market_price, resolution, days_to_resolve)

    return {
        "true_prob": true_prob,
        "market_price": market_price,
        "our_estimate": our_estimate,
        "side": side,
        "resolution": resolution,
        "days_to_resolve": days_to_resolve,
        "daily_prices": daily_prices,
    }


def _generate_price_path(
    start_price: float,
    resolution: float,
    days: int,
) -> list[float]:
    """Generate a realistic daily price path from start to resolution.

    Prices drift toward the resolution value with increasing certainty
    and random volatility.
    """
    prices = [start_price]
    for day in range(1, days + 1):
        progress = day / days
        # Pull toward resolution (stronger as resolution approaches)
        pull_strength = progress ** 2
        target = start_price * (1 - pull_strength) + resolution * pull_strength
        # Add noise (decreasing as resolution nears)
        noise_scale = 0.05 * (1 - progress * 0.7)
        noise = random.gauss(0, noise_scale)
        new_price = target + noise
        new_price = max(0.01, min(0.99, new_price))
        prices.append(new_price)
    return prices


def simulate_hold_strategy(scenarios: list[dict]) -> StrategyResult:
    """Simulate hold-to-resolution strategy."""
    result = StrategyResult(name="Hold-to-Resolution")

    for i, s in enumerate(scenarios):
        if s["side"] == "hold":
            continue

        entry_price = s["market_price"]
        resolution = s["resolution"]
        side = s["side"]
        days = s["days_to_resolve"]

        if side == "buy_yes":
            cost = entry_price * POSITION_SIZE_USD / entry_price  # shares
            shares = POSITION_SIZE_USD / entry_price
            payout = shares * (1.0 - WINNER_FEE) if resolution == 1.0 else 0.0
            pnl = payout - POSITION_SIZE_USD
        else:  # buy_no
            no_price = 1.0 - entry_price
            shares = POSITION_SIZE_USD / no_price
            payout = shares * (1.0 - WINNER_FEE) if resolution == 0.0 else 0.0
            pnl = payout - POSITION_SIZE_USD

        result.trades.append(TradeResult(
            market_id=i,
            side=side,
            entry_price=entry_price,
            exit_price=resolution,
            resolution=resolution,
            estimated_prob=s["our_estimate"],
            hold_days=days,
            pnl=pnl,
            exit_reason="resolution",
            capital_deployed=POSITION_SIZE_USD,
        ))

    return result


def simulate_active_exit_strategy(scenarios: list[dict]) -> StrategyResult:
    """Simulate active exit strategy with edge capture, stop loss, and time decay."""
    result = StrategyResult(name="Active-Exit")

    for i, s in enumerate(scenarios):
        if s["side"] == "hold":
            continue

        entry_price = s["market_price"]
        side = s["side"]
        estimated_prob = s["our_estimate"]
        daily_prices = s["daily_prices"]

        exit_price = None
        exit_day = None
        exit_reason = None

        for day, price in enumerate(daily_prices[1:], 1):  # Skip entry day
            # Check exit conditions
            reason = _check_exit_conditions(
                side=side,
                entry_price=entry_price,
                current_price=price,
                estimated_prob=estimated_prob,
                hold_days=day,
            )
            if reason:
                exit_price = price
                exit_day = day
                exit_reason = reason
                break

        # If no exit triggered, hold to resolution
        if exit_price is None:
            exit_price = s["resolution"]
            exit_day = s["days_to_resolve"]
            exit_reason = "resolution"

        # Calculate P&L
        if side == "buy_yes":
            shares = POSITION_SIZE_USD / entry_price
            if exit_reason == "resolution":
                payout = shares * (1.0 - WINNER_FEE) if s["resolution"] == 1.0 else 0.0
            else:
                payout = shares * exit_price  # Sell at market price
            pnl = payout - POSITION_SIZE_USD
        else:  # buy_no
            no_entry = 1.0 - entry_price
            shares = POSITION_SIZE_USD / no_entry
            if exit_reason == "resolution":
                payout = shares * (1.0 - WINNER_FEE) if s["resolution"] == 0.0 else 0.0
            else:
                no_exit_value = 1.0 - exit_price
                payout = shares * no_exit_value
            pnl = payout - POSITION_SIZE_USD

        result.trades.append(TradeResult(
            market_id=i,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            resolution=s["resolution"] if exit_reason == "resolution" else None,
            estimated_prob=estimated_prob,
            hold_days=exit_day,
            pnl=pnl,
            exit_reason=exit_reason,
            capital_deployed=POSITION_SIZE_USD,
        ))

    return result


def _check_exit_conditions(
    side: str,
    entry_price: float,
    current_price: float,
    estimated_prob: float,
    hold_days: int,
) -> Optional[str]:
    """Check if any exit condition is met. Returns exit reason or None."""

    if side == "buy_yes":
        target = estimated_prob
        edge_total = target - entry_price
        edge_captured = current_price - entry_price

        # Edge captured
        if edge_total > 0 and edge_captured / edge_total >= EDGE_CAPTURE_PCT:
            return "edge_captured"

        # Stop loss
        if entry_price - current_price > STOP_LOSS_PCT:
            return "stop_loss"

    elif side == "buy_no":
        no_entry = 1.0 - entry_price
        no_current = 1.0 - current_price
        no_target = estimated_prob  # Our estimate of P(NO)... wait
        # Actually for buy_no: estimated_prob is P(YES), so P(NO) = 1 - estimated_prob
        # We want YES price to fall. Target YES price ≈ estimated_prob (which is low if we're buying NO)
        target_yes = estimated_prob
        edge_total = entry_price - target_yes  # We want YES to drop from entry to target
        edge_captured = entry_price - current_price

        if edge_total > 0 and edge_captured / edge_total >= EDGE_CAPTURE_PCT:
            return "edge_captured"

        # Stop loss: YES price rose
        if current_price - entry_price > STOP_LOSS_PCT:
            return "stop_loss"

    # Time decay
    if hold_days >= TIME_DECAY_DAYS:
        if abs(current_price - entry_price) < TIME_DECAY_MOVEMENT:
            return "time_decay"

    return None


def run_comparison() -> dict:
    """Run the full backtest comparison and return results."""
    print("=" * 70)
    print("BACKTEST: Hold-to-Resolution vs Active-Exit Strategy")
    print("=" * 70)
    print(f"Markets simulated: {NUM_MARKETS}")
    print(f"Position size: ${POSITION_SIZE_USD}")
    print(f"Exit thresholds: edge_capture={EDGE_CAPTURE_PCT:.0%}, "
          f"stop_loss={STOP_LOSS_PCT:.0%}, time_decay={TIME_DECAY_DAYS}d")
    print()

    # Generate scenarios
    scenarios = [generate_market_scenario() for _ in range(NUM_MARKETS)]
    actionable = sum(1 for s in scenarios if s["side"] != "hold")
    print(f"Actionable signals (edge detected): {actionable}/{NUM_MARKETS}")
    print()

    # Run both strategies
    hold_result = simulate_hold_strategy(scenarios)
    exit_result = simulate_active_exit_strategy(scenarios)

    # Print comparison
    print(f"{'Metric':<35} {'Hold-to-Res':>15} {'Active-Exit':>15} {'Delta':>12}")
    print("-" * 77)

    metrics = [
        ("Total P&L ($)", hold_result.total_pnl, exit_result.total_pnl),
        ("Avg P&L per trade ($)", hold_result.avg_pnl_per_trade, exit_result.avg_pnl_per_trade),
        ("Win Rate (%)", hold_result.win_rate, exit_result.win_rate),
        ("Avg Hold (days)", hold_result.avg_hold_days, exit_result.avg_hold_days),
        ("Max Drawdown ($)", hold_result.max_drawdown, exit_result.max_drawdown),
        ("Capital Velocity (ann.)", hold_result.capital_velocity, exit_result.capital_velocity),
        ("Total Dollar-Days", hold_result.total_dollar_days, exit_result.total_dollar_days),
        ("Trade Count", len(hold_result.trades), len(exit_result.trades)),
    ]

    for name, hold_val, exit_val in metrics:
        delta = exit_val - hold_val
        delta_str = f"{delta:+.2f}"
        if name in ("Avg Hold (days)", "Max Drawdown ($)", "Total Dollar-Days"):
            # Lower is better for these
            delta_str = f"{delta:+.2f}" + (" ✓" if delta < 0 else "")
        else:
            delta_str = f"{delta:+.2f}" + (" ✓" if delta > 0 else "")

        print(f"{name:<35} {hold_val:>15.2f} {exit_val:>15.2f} {delta_str:>12}")

    # Exit reason breakdown
    print()
    print("Active-Exit Breakdown by Reason:")
    print("-" * 50)
    reason_counts: dict[str, list[TradeResult]] = {}
    for t in exit_result.trades:
        reason_counts.setdefault(t.exit_reason, []).append(t)

    for reason, trades in sorted(reason_counts.items()):
        count = len(trades)
        pnl = sum(t.pnl for t in trades)
        avg_days = statistics.mean(t.hold_days for t in trades)
        win_rate = sum(1 for t in trades if t.pnl > 0) / count * 100
        print(f"  {reason:<20} count={count:>4}  P&L=${pnl:>8.2f}  "
              f"avg_hold={avg_days:>5.1f}d  win_rate={win_rate:>5.1f}%")

    # Capital efficiency analysis
    print()
    print("Capital Efficiency Analysis:")
    print("-" * 50)
    hold_capital_turns = hold_result.total_pnl / (INITIAL_BANKROLL * hold_result.avg_hold_days / 365) if hold_result.avg_hold_days > 0 else 0
    exit_capital_turns = exit_result.total_pnl / (INITIAL_BANKROLL * exit_result.avg_hold_days / 365) if exit_result.avg_hold_days > 0 else 0

    print(f"  Hold: avg capital locked {hold_result.avg_hold_days:.1f} days/trade")
    print(f"  Exit: avg capital locked {exit_result.avg_hold_days:.1f} days/trade")
    speedup = hold_result.avg_hold_days / exit_result.avg_hold_days if exit_result.avg_hold_days > 0 else 0
    print(f"  Capital turnover speedup: {speedup:.1f}x")
    print(f"  Dollar-days saved: {hold_result.total_dollar_days - exit_result.total_dollar_days:,.0f}")

    velocity_improvement = (
        (exit_result.capital_velocity - hold_result.capital_velocity)
        / abs(hold_result.capital_velocity) * 100
        if hold_result.capital_velocity != 0 else 0
    )
    print(f"  Capital velocity improvement: {velocity_improvement:+.1f}%")

    print()
    print("=" * 70)

    return {
        "hold": hold_result,
        "active_exit": exit_result,
        "scenarios": scenarios,
    }


if __name__ == "__main__":
    run_comparison()
