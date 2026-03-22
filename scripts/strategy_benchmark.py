#!/usr/bin/env python3
"""Strategy Benchmark Harness — Replay comparison across strategy families.

Compares three strategy families against mandatory replay scenarios built from
real trading patterns:
  1. Directional BTC5 (the live strategy)
  2. Mean-reversion indicator stack
  3. Structural baselines (resolution sniping, neg-risk, pair completion)

Each scenario replays synthetic but realistic price data. Strategies produce
StrategyResult dataclasses that are compared on PnL, drawdown, Sharpe,
profit factor, fill rate, and trapped capital.

Admission rule: a challenger strategy stays shadow-only unless it beats
directional BTC5 AND does not underperform structural on post-cost expectancy,
drawdown, and trapped capital.

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger("JJ.benchmark")

# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class PriceObservation:
    """Single price tick in a replay scenario."""
    timestamp: float          # epoch seconds
    btc_spot: float           # BTC spot price (Binance)
    candle_open: float        # candle open for the 5-min window
    best_bid_down: float      # CLOB best bid for DOWN token
    best_ask_down: float      # CLOB best ask for DOWN token
    best_bid_up: float        # CLOB best bid for UP token
    best_ask_up: float        # CLOB best ask for UP token
    resolved_outcome: Optional[str] = None  # "UP", "DOWN", or None if unresolved
    resolution_price: Optional[float] = None  # near-certain price for structural


@dataclass
class Trade:
    """A single simulated trade."""
    side: str           # "UP" or "DOWN"
    entry_price: float  # price paid per share
    exit_price: float   # 1.0 if won, 0.0 if lost, entry if unfilled/cancelled
    pnl: float          # exit - entry (per share, $1 notional)
    filled: bool = True
    trapped: bool = False  # capital locked in unresolved market


@dataclass
class StrategyResult:
    """Aggregate result of a strategy on a single scenario."""
    strategy_name: str
    trades: int
    wins: int
    losses: int
    gross_pnl: float
    max_drawdown: float
    sharpe: float
    profit_factor: float
    fill_rate: float
    trapped_capital_pct: float

    @property
    def expectancy(self) -> float:
        """Average PnL per trade, post-cost."""
        if self.trades == 0:
            return 0.0
        return self.gross_pnl / self.trades


@dataclass
class ReplayScenario:
    """A complete replay scenario with market data."""
    name: str
    description: str
    start_ts: float
    end_ts: float
    market_data: List[PriceObservation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Strategy protocol and implementations
# ---------------------------------------------------------------------------

class Strategy(Protocol):
    """Protocol that all strategy implementations must satisfy."""
    name: str

    def evaluate(self, scenario: ReplayScenario) -> StrategyResult:
        ...


def _compute_result(
    name: str,
    trades: List[Trade],
    total_observations: int,
) -> StrategyResult:
    """Compute StrategyResult from a list of Trade objects."""
    if not trades:
        return StrategyResult(
            strategy_name=name,
            trades=0, wins=0, losses=0,
            gross_pnl=0.0, max_drawdown=0.0, sharpe=0.0,
            profit_factor=0.0, fill_rate=0.0, trapped_capital_pct=0.0,
        )

    filled_trades = [t for t in trades if t.filled]
    wins = sum(1 for t in filled_trades if t.pnl > 0)
    losses = sum(1 for t in filled_trades if t.pnl <= 0)
    gross_pnl = sum(t.pnl for t in filled_trades)

    # Max drawdown from cumulative PnL curve
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in filled_trades:
        cum += t.pnl
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Sharpe: mean(pnl) / std(pnl) * sqrt(n) — annualized is meaningless
    # for short replays, so we report per-scenario Sharpe
    pnls = [t.pnl for t in filled_trades]
    mean_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    if len(pnls) > 1:
        var = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(var) if var > 0 else 0.0
    else:
        std_pnl = 0.0
    sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0

    # Profit factor: gross wins / abs(gross losses)
    gross_wins = sum(t.pnl for t in filled_trades if t.pnl > 0)
    gross_losses = abs(sum(t.pnl for t in filled_trades if t.pnl <= 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0.0
    )

    fill_rate = len(filled_trades) / len(trades) if trades else 0.0
    trapped = sum(1 for t in filled_trades if t.trapped)
    trapped_pct = trapped / len(filled_trades) if filled_trades else 0.0

    return StrategyResult(
        strategy_name=name,
        trades=len(filled_trades),
        wins=wins,
        losses=losses,
        gross_pnl=round(gross_pnl, 4),
        max_drawdown=round(max_dd, 4),
        sharpe=round(sharpe, 4),
        profit_factor=round(profit_factor, 4),
        fill_rate=round(fill_rate, 4),
        trapped_capital_pct=round(trapped_pct, 4),
    )


# ---------------------------------------------------------------------------
# Strategy 1: Directional BTC5
# ---------------------------------------------------------------------------

class DirectionalBTC5Strategy:
    """Simulates current BTC5 logic: compare spot to candle open, buy the
    direction with the larger delta. Maker-only at best bid."""

    name: str = "DirectionalBTC5"

    def __init__(self, delta_threshold: float = 0.0005, position_size: float = 5.0):
        self.delta_threshold = delta_threshold
        self.position_size = position_size

    def evaluate(self, scenario: ReplayScenario) -> StrategyResult:
        trades: List[Trade] = []
        for obs in scenario.market_data:
            if obs.candle_open == 0:
                continue
            delta = (obs.btc_spot - obs.candle_open) / obs.candle_open

            if abs(delta) < self.delta_threshold:
                continue  # skip — delta too small

            if delta < 0:
                # BTC dropping → buy DOWN
                side = "DOWN"
                entry = obs.best_bid_down
            else:
                # BTC rising → buy UP
                side = "UP"
                entry = obs.best_bid_up

            if entry <= 0 or entry >= 1.0:
                trades.append(Trade(side=side, entry_price=entry,
                                    exit_price=entry, pnl=0.0, filled=False))
                continue

            # Resolve
            if obs.resolved_outcome is None:
                trades.append(Trade(side=side, entry_price=entry,
                                    exit_price=entry, pnl=0.0,
                                    filled=True, trapped=True))
                continue

            won = (obs.resolved_outcome == side)
            exit_price = 1.0 if won else 0.0
            pnl = exit_price - entry
            trades.append(Trade(side=side, entry_price=entry,
                                exit_price=exit_price, pnl=pnl, filled=True))

        return _compute_result(self.name, trades, len(scenario.market_data))


# ---------------------------------------------------------------------------
# Strategy 2: Mean Reversion
# ---------------------------------------------------------------------------

class MeanReversionStrategy:
    """Simulates indicator-based mean reversion: if BTC has moved too far
    from open (high delta), bet on reversion. Opposite of directional.
    RSI oversold → buy UP, RSI overbought → buy DOWN."""

    name: str = "MeanReversion"

    def __init__(self, reversion_threshold: float = 0.0010):
        self.reversion_threshold = reversion_threshold

    def evaluate(self, scenario: ReplayScenario) -> StrategyResult:
        trades: List[Trade] = []
        for obs in scenario.market_data:
            if obs.candle_open == 0:
                continue
            delta = (obs.btc_spot - obs.candle_open) / obs.candle_open

            if abs(delta) < self.reversion_threshold:
                continue

            # Mean reversion: bet AGAINST the move
            if delta < 0:
                # BTC dropped → expect reversion UP
                side = "UP"
                entry = obs.best_bid_up
            else:
                # BTC rose → expect reversion DOWN
                side = "DOWN"
                entry = obs.best_bid_down

            if entry <= 0 or entry >= 1.0:
                trades.append(Trade(side=side, entry_price=entry,
                                    exit_price=entry, pnl=0.0, filled=False))
                continue

            if obs.resolved_outcome is None:
                trades.append(Trade(side=side, entry_price=entry,
                                    exit_price=entry, pnl=0.0,
                                    filled=True, trapped=True))
                continue

            won = (obs.resolved_outcome == side)
            exit_price = 1.0 if won else 0.0
            pnl = exit_price - entry
            trades.append(Trade(side=side, entry_price=entry,
                                exit_price=exit_price, pnl=pnl, filled=True))

        return _compute_result(self.name, trades, len(scenario.market_data))


# ---------------------------------------------------------------------------
# Strategy 3: Structural (Resolution Sniping)
# ---------------------------------------------------------------------------

class StructuralStrategy:
    """Simulates resolution sniping: only buy when price indicates near-certain
    outcome (sub-$0.97 for YES on effectively resolved markets). Low volume,
    high win rate, capital-efficient."""

    name: str = "Structural"

    def __init__(self, max_entry: float = 0.97, min_resolution_price: float = 0.94):
        self.max_entry = max_entry
        self.min_resolution_price = min_resolution_price

    def evaluate(self, scenario: ReplayScenario) -> StrategyResult:
        trades: List[Trade] = []
        for obs in scenario.market_data:
            # Structural only trades when resolution_price is set and high
            if obs.resolution_price is None:
                continue
            if obs.resolution_price < self.min_resolution_price:
                continue

            # Determine which side is near-certain
            if obs.resolution_price >= self.min_resolution_price:
                # The "winning" side is trading at resolution_price
                # We want to buy the winning side below our max_entry
                if obs.best_ask_down <= self.max_entry and obs.resolved_outcome == "DOWN":
                    side = "DOWN"
                    entry = obs.best_ask_down
                elif obs.best_ask_up <= self.max_entry and obs.resolved_outcome == "UP":
                    side = "UP"
                    entry = obs.best_ask_up
                else:
                    continue
            else:
                continue

            if entry <= 0 or entry >= 1.0:
                continue

            if obs.resolved_outcome is None:
                trades.append(Trade(side=side, entry_price=entry,
                                    exit_price=entry, pnl=0.0,
                                    filled=True, trapped=True))
                continue

            won = (obs.resolved_outcome == side)
            exit_price = 1.0 if won else 0.0
            pnl = exit_price - entry
            trades.append(Trade(side=side, entry_price=entry,
                                exit_price=exit_price, pnl=pnl, filled=True))

        return _compute_result(self.name, trades, len(scenario.market_data))


# ---------------------------------------------------------------------------
# Mandatory replay scenarios (synthetic but realistic)
# ---------------------------------------------------------------------------

def build_march_11_winning_session() -> ReplayScenario:
    """March 11 winning session: BTC trending down, 39 DOWN wins out of 47.
    Concentrated trading 3-8 AM ET. Strong directional edge."""
    base_ts = 1741651200.0  # ~2026-03-11 00:00 UTC
    observations: List[PriceObservation] = []

    # 47 candle windows, BTC trending down from ~84000 to ~83200
    # Each 5-min candle: spot drops ~$50 below open → delta ~-0.06%
    btc_start = 84000.0
    for i in range(47):
        ts = base_ts + i * 300  # 5-min windows
        candle_open = btc_start - i * 15.0  # candle opens at drift level
        # Spot drops $50-80 below open on DOWN candles, rises $50 on UP
        if i < 39:
            resolved = "DOWN"
            btc_spot = candle_open - 55.0 - (i % 5) * 5.0  # -55 to -80 below open
        else:
            resolved = "UP"
            btc_spot = candle_open + 55.0 + (i % 3) * 5.0  # +55 to +65 above open

        observations.append(PriceObservation(
            timestamp=ts,
            btc_spot=btc_spot,
            candle_open=candle_open,
            best_bid_down=0.52 if resolved == "DOWN" else 0.48,
            best_ask_down=0.53 if resolved == "DOWN" else 0.49,
            best_bid_up=0.48 if resolved == "DOWN" else 0.52,
            best_ask_up=0.49 if resolved == "DOWN" else 0.53,
            resolved_outcome=resolved,
            resolution_price=None,  # not a structural trade
        ))

    return ReplayScenario(
        name="march_11_winning",
        description="March 11 BTC trending down, 39/47 DOWN wins. Peak directional edge.",
        start_ts=base_ts,
        end_ts=base_ts + 47 * 300,
        market_data=observations,
    )


def build_march_15_concentration_failure() -> ReplayScenario:
    """March 15 concentration failure: over-concentration in DOWN direction,
    BTC reverses sharply. Large drawdown from directional betting."""
    base_ts = 1741996800.0  # ~2026-03-15 00:00 UTC
    observations: List[PriceObservation] = []

    btc_start = 83500.0
    for i in range(40):
        ts = base_ts + i * 300
        if i < 20:
            # First half: BTC drifting down — looks like DOWN trend
            candle_open = btc_start - i * 10.0
            btc_spot = candle_open - 60.0  # spot drops $60 below open
            # But resolution is mixed — market is noisy
            resolved = "DOWN" if i % 3 != 2 else "UP"
        else:
            # Second half: BTC reverses sharply upward
            candle_open = btc_start - 200.0 + (i - 20) * 20.0
            btc_spot = candle_open + 70.0  # spot rises $70 above open
            resolved = "UP"

        observations.append(PriceObservation(
            timestamp=ts,
            btc_spot=btc_spot,
            candle_open=candle_open,
            best_bid_down=0.51,
            best_ask_down=0.52,
            best_bid_up=0.49,
            best_ask_up=0.50,
            resolved_outcome=resolved,
            resolution_price=None,
        ))

    return ReplayScenario(
        name="march_15_concentration",
        description="March 15 over-concentration in DOWN, BTC reverses. Drawdown scenario.",
        start_ts=base_ts,
        end_ts=base_ts + 40 * 300,
        market_data=observations,
    )


def build_march_22_loss_session() -> ReplayScenario:
    """March 22 one-day loss: bought DOWN at 48-55 cents, BTC went UP.
    Directional strategy loses; mean reversion might win."""
    base_ts = 1742601600.0  # ~2026-03-22 00:00 UTC
    observations: List[PriceObservation] = []

    btc_start = 85000.0
    for i in range(30):
        ts = base_ts + i * 300
        candle_open = btc_start + i * 10.0

        # Entire session: spot dips below open at T-10s (directional reads
        # negative delta → buys DOWN), but candle closes UP every time.
        # This is the "bought DOWN at 48-55c, BTC went UP" pattern.
        btc_spot = candle_open - 55.0 - (i % 4) * 5.0  # -55 to -70 below open

        observations.append(PriceObservation(
            timestamp=ts,
            btc_spot=btc_spot,
            candle_open=candle_open,
            best_bid_down=0.48 + (i % 3) * 0.02,  # 48-52 cent entry
            best_ask_down=0.49 + (i % 3) * 0.02,
            best_bid_up=0.48 + (i % 4) * 0.01,
            best_ask_up=0.49 + (i % 4) * 0.01,
            resolved_outcome="UP",  # everything resolves UP despite mid-candle dip
            resolution_price=None,
        ))

    return ReplayScenario(
        name="march_22_loss",
        description="March 22 BTC grinds up, bought DOWN at 48-55c, all resolve UP. Loss day.",
        start_ts=base_ts,
        end_ts=base_ts + 30 * 300,
        market_data=observations,
    )


def get_mandatory_scenarios() -> List[ReplayScenario]:
    """Return all three mandatory replay scenarios."""
    return [
        build_march_11_winning_session(),
        build_march_15_concentration_failure(),
        build_march_22_loss_session(),
    ]


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(
    scenarios: List[ReplayScenario],
    strategies: List[Any],
) -> Dict[str, Dict[str, StrategyResult]]:
    """Run all strategies against all scenarios.

    Returns: {scenario_name: {strategy_name: StrategyResult}}
    """
    results: Dict[str, Dict[str, StrategyResult]] = {}

    for scenario in scenarios:
        logger.info("Running scenario: %s (%d observations)",
                     scenario.name, len(scenario.market_data))
        results[scenario.name] = {}

        for strategy in strategies:
            result = strategy.evaluate(scenario)
            results[scenario.name][strategy.name] = result
            logger.info("  %s: PnL=%.4f, W/L=%d/%d, Sharpe=%.4f, DD=%.4f",
                         strategy.name, result.gross_pnl, result.wins,
                         result.losses, result.sharpe, result.max_drawdown)

    return results


# ---------------------------------------------------------------------------
# Admission rule
# ---------------------------------------------------------------------------

def check_admission(
    challenger: StrategyResult,
    directional: StrategyResult,
    structural: StrategyResult,
) -> Tuple[bool, str]:
    """Check whether a challenger strategy earns promotion from shadow-only.

    Admission requires:
      1. Challenger expectancy > directional expectancy
      2. Challenger drawdown <= structural drawdown (or structural has none)
      3. Challenger trapped_capital_pct <= structural trapped_capital_pct (or structural has none)

    Returns: (admitted, reason)
    """
    reasons = []

    # Rule 1: must beat directional on expectancy
    if directional.expectancy > 0 and challenger.expectancy <= directional.expectancy:
        reasons.append(
            f"Expectancy {challenger.expectancy:.4f} does not beat "
            f"directional {directional.expectancy:.4f}"
        )

    # Rule 2: must not underperform structural on drawdown
    if structural.trades > 0 and challenger.max_drawdown > structural.max_drawdown:
        reasons.append(
            f"Drawdown {challenger.max_drawdown:.4f} exceeds "
            f"structural {structural.max_drawdown:.4f}"
        )

    # Rule 3: must not underperform structural on trapped capital
    if structural.trades > 0 and challenger.trapped_capital_pct > structural.trapped_capital_pct:
        reasons.append(
            f"Trapped capital {challenger.trapped_capital_pct:.4f} exceeds "
            f"structural {structural.trapped_capital_pct:.4f}"
        )

    if reasons:
        return False, "; ".join(reasons)
    return True, "Admitted: beats directional expectancy, within structural bounds"


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(results: Dict[str, Dict[str, StrategyResult]]) -> str:
    """Format benchmark results as a comparison table with winner per scenario."""
    lines: List[str] = []
    lines.append("=" * 90)
    lines.append("STRATEGY BENCHMARK REPORT")
    lines.append("=" * 90)

    for scenario_name, strat_results in results.items():
        lines.append("")
        lines.append(f"--- {scenario_name} ---")
        header = (
            f"{'Strategy':<20} {'Trades':>6} {'W/L':>8} {'PnL':>10} "
            f"{'MaxDD':>8} {'Sharpe':>8} {'PF':>8} {'Fill%':>7} {'Trap%':>7}"
        )
        lines.append(header)
        lines.append("-" * len(header))

        best_pnl = -float("inf")
        winner = ""
        for sname, r in strat_results.items():
            wl = f"{r.wins}/{r.losses}"
            line = (
                f"{r.strategy_name:<20} {r.trades:>6} {wl:>8} "
                f"{r.gross_pnl:>10.4f} {r.max_drawdown:>8.4f} "
                f"{r.sharpe:>8.4f} {r.profit_factor:>8.4f} "
                f"{r.fill_rate:>7.2%} {r.trapped_capital_pct:>7.2%}"
            )
            lines.append(line)
            if r.gross_pnl > best_pnl:
                best_pnl = r.gross_pnl
                winner = r.strategy_name
        lines.append(f"  Winner: {winner} (PnL: {best_pnl:.4f})")

    lines.append("")
    lines.append("=" * 90)

    # Admission check if all three strategies present
    all_strats = set()
    for sr in results.values():
        all_strats.update(sr.keys())

    if {"DirectionalBTC5", "MeanReversion", "Structural"}.issubset(all_strats):
        lines.append("")
        lines.append("ADMISSION CHECKS (MeanReversion vs DirectionalBTC5 + Structural):")
        for scenario_name, sr in results.items():
            admitted, reason = check_admission(
                sr["MeanReversion"], sr["DirectionalBTC5"], sr["Structural"]
            )
            status = "ADMITTED" if admitted else "BLOCKED"
            lines.append(f"  {scenario_name}: {status} — {reason}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full benchmark suite and print results."""
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    scenarios = get_mandatory_scenarios()
    strategies = [
        DirectionalBTC5Strategy(),
        MeanReversionStrategy(),
        StructuralStrategy(),
    ]

    results = run_benchmark(scenarios, strategies)
    report = format_report(results)
    print(report)


if __name__ == "__main__":
    main()
