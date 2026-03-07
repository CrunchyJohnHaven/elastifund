"""Advanced Monte Carlo simulation engine with sophisticated market models.

Features:
- Regime-switching (bull/bear/crisis)
- Fat-tailed distributions (Student-t)
- Correlated market movements
- Dynamic Kelly adjustment based on rolling win rate
- Drawdown-conditional position scaling
- Market impact modeling
- Time-varying edge decay
- Liquidity constraints
- Capital injection schedule
- Confidence bands (p5-p95)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from monte_carlo import load_empirical_trades

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@dataclass
class RegimeParams:
    """Parameters for market regime."""

    name: str
    win_rate_mult: float  # Multiplier for base win rate
    volatility_mult: float  # Multiplier for outcome volatility
    transition_probs: list[float]  # [P(bull), P(bear), P(crisis)] from this regime


@dataclass
class SimulationConfig:
    """Configuration for advanced Monte Carlo simulation."""

    # Capital and timing
    starting_capital: float = 75.0
    capital_injection_weekly: float = 1.0
    weeks: int = 52
    trades_per_day: int = 5
    days_per_year: float = 365.0

    # Sizing
    use_kelly: bool = True
    kelly_base_multiplier: float = 0.25
    kelly_max_multiplier: float = 0.75
    position_min: float = 0.50
    position_max: float = 10.0

    # Kelly adjustment
    dynamic_kelly: bool = True
    kelly_lookback_trades: int = 20
    kelly_reduction_on_losing_streak: float = 0.5

    # Drawdown management
    max_drawdown_allowed: float = 0.40
    drawdown_scaling_smooth: bool = True
    drawdown_scaling_exponent: float = 2.0

    # Market impact
    model_market_impact: bool = True
    impact_coefficient: float = 0.001  # Basis points per sqrt(size/volume)

    # Edge decay
    model_edge_decay: bool = True
    edge_decay_half_life_days: float = 180.0

    # Liquidity
    model_liquidity: bool = True
    avg_order_book_depth: float = 100.0  # Dollars at $0.50 entry
    participation_rate: float = 0.10  # Max 10% of book per trade

    # Regimes
    enable_regimes: bool = True
    regime_transition_days: int = 30

    # Distributions
    use_fat_tails: bool = True
    student_t_df: float = 4.0  # Degrees of freedom

    # Infrastructure
    infra_cost_monthly: float = 20.0

    # Simulation
    num_paths: int = 10000
    random_seed: int | None = 42


class RegimeSwitchingModel:
    """Market regime-switching model (bull/bear/crisis)."""

    def __init__(self, config: SimulationConfig):
        """Initialize regime model with transition matrix."""
        self.config = config

        # Define regimes: bull (high edge), bear (low edge), crisis (very low + vol)
        self.regimes = {
            "bull": RegimeParams(
                name="bull",
                win_rate_mult=1.15,  # Higher win rate
                volatility_mult=0.9,  # Lower volatility
                transition_probs=[0.70, 0.25, 0.05],  # P(stay bull, go bear, go crisis)
            ),
            "bear": RegimeParams(
                name="bear",
                win_rate_mult=0.95,  # Lower win rate
                volatility_mult=1.2,  # Higher volatility
                transition_probs=[0.30, 0.60, 0.10],  # P(go bull, stay bear, go crisis)
            ),
            "crisis": RegimeParams(
                name="crisis",
                win_rate_mult=0.75,  # Much lower win rate
                volatility_mult=1.8,  # Much higher volatility
                transition_probs=[0.10, 0.40, 0.50],  # P(go bull, go bear, stay crisis)
            ),
        }

        self.current_regime = "bull"
        self.regime_start_day = 0

    def step(self, day: int) -> str:
        """Update regime at regime_transition_days intervals."""
        if day - self.regime_start_day >= self.config.regime_transition_days:
            probs = self.regimes[self.current_regime].transition_probs
            regime_names = ["bull", "bear", "crisis"]
            self.current_regime = np.random.choice(regime_names, p=probs)
            self.regime_start_day = day
        return self.current_regime

    def get_regime_params(self) -> RegimeParams:
        """Get current regime parameters."""
        return self.regimes[self.current_regime]


class FatTailedDistribution:
    """Fat-tailed distribution sampling (Student-t)."""

    def __init__(self, df: float = 4.0):
        """Initialize with degrees of freedom."""
        self.df = df

    def sample(self, size: int = 1) -> np.ndarray:
        """Sample from Student-t distribution."""
        # Standardized t-distribution, scale to reasonable range
        return np.random.standard_t(self.df, size=size) * 0.3


class CorrelationStructure:
    """Correlated market movements using copulas concept."""

    def __init__(self, base_correlation: float = 0.3):
        """Initialize correlation structure."""
        self.base_correlation = base_correlation

    def get_correlated_outcomes(
        self, num_trades: int, base_win_rate: float
    ) -> np.ndarray:
        """Generate correlated Bernoulli outcomes.

        Args:
            num_trades: Number of trades to correlate
            base_win_rate: Base probability of winning

        Returns:
            Array of win/loss outcomes (1/0)
        """
        # Use Archimedean copula concept: shared frailty
        # Draw a shared component affecting all trades in group
        shared_component = np.random.uniform(0, 1)

        # Weight between shared and independent
        results = np.zeros(num_trades, dtype=int)
        for i in range(num_trades):
            # Blend shared and independent components
            effective_prob = (
                self.base_correlation * shared_component
                + (1 - self.base_correlation) * np.random.uniform(0, 1)
            )
            results[i] = 1 if effective_prob < base_win_rate else 0

        return results


class AdvancedMonteCarloEngine:
    """Advanced Monte Carlo simulation with sophisticated market models."""

    def __init__(self, empirical_trades: list[dict], config: SimulationConfig):
        """Initialize simulation engine.

        Args:
            empirical_trades: List of trade outcomes from load_empirical_trades()
            config: SimulationConfig object
        """
        self.empirical_trades = empirical_trades
        self.config = config

        if config.random_seed is not None:
            np.random.seed(config.random_seed)

        # Compute empirical statistics
        self.empirical_win_rate = sum(1 for t in empirical_trades if t["won"]) / max(
            len(empirical_trades), 1
        )
        self.empirical_pnl_std = np.std(
            [t["pnl_pct"] for t in empirical_trades], ddof=1
        )

        # Initialize models
        self.regime_model = (
            RegimeSwitchingModel(config) if config.enable_regimes else None
        )
        self.fat_tail_dist = (
            FatTailedDistribution(config.student_t_df) if config.use_fat_tails else None
        )
        self.correlation_model = CorrelationStructure(base_correlation=0.25)

    def get_regime_adjusted_win_rate(self, base_rate: float) -> float:
        """Adjust win rate based on current regime."""
        if self.regime_model is None:
            return base_rate

        regime_params = self.regime_model.get_regime_params()
        adjusted = base_rate * regime_params.win_rate_mult
        return np.clip(adjusted, 0.0, 1.0)

    def get_rolling_win_rate(self, trade_history: list[dict], lookback: int) -> float:
        """Compute rolling win rate over last N trades."""
        if len(trade_history) == 0:
            return self.empirical_win_rate

        start_idx = max(0, len(trade_history) - lookback)
        recent = trade_history[start_idx:]
        if len(recent) == 0:
            return self.empirical_win_rate

        return sum(1 for t in recent if t.get("won", False)) / len(recent)

    def compute_dynamic_kelly_multiplier(
        self, rolling_win_rate: float, losing_streak_length: int
    ) -> float:
        """Compute Kelly multiplier adjusted by rolling performance.

        Args:
            rolling_win_rate: Win rate over last N trades
            losing_streak_length: Consecutive losses

        Returns:
            Adjusted Kelly multiplier
        """
        if not self.config.dynamic_kelly:
            return self.config.kelly_base_multiplier

        # Base multiplier from config
        base_mult = self.config.kelly_base_multiplier

        # Adjust by rolling win rate deviation from empirical
        win_rate_diff = rolling_win_rate - self.empirical_win_rate
        # Scale adjustment: +5% win rate gives ~5-10% boost
        win_rate_adjustment = 1.0 + (win_rate_diff * 2.0)

        # Reduce on losing streaks
        if losing_streak_length > 2:
            losing_streak_reduction = self.config.kelly_reduction_on_losing_streak ** (
                losing_streak_length - 2
            )
        else:
            losing_streak_reduction = 1.0

        adjusted_mult = base_mult * win_rate_adjustment * losing_streak_reduction
        return np.clip(
            adjusted_mult,
            self.config.kelly_base_multiplier * 0.3,
            self.config.kelly_max_multiplier,
        )

    def compute_drawdown_scaling(
        self, current_capital: float, peak_capital: float
    ) -> float:
        """Compute position scaling factor based on drawdown.

        Args:
            current_capital: Current account value
            peak_capital: Peak account value

        Returns:
            Scaling factor [0, 1]
        """
        if peak_capital <= 0:
            return 1.0

        drawdown = (peak_capital - current_capital) / peak_capital
        max_dd = self.config.max_drawdown_allowed

        if drawdown >= max_dd:
            return 0.0  # No trading at max drawdown

        if drawdown <= 0:
            return 1.0  # Full sizing at no drawdown

        if self.config.drawdown_scaling_smooth:
            # Smooth reduction: (1 - drawdown/max_dd)^exponent
            reduction_ratio = drawdown / max_dd
            scaling = (1.0 - reduction_ratio) ** self.config.drawdown_scaling_exponent
        else:
            # Linear reduction
            scaling = 1.0 - (drawdown / max_dd)

        return np.clip(scaling, 0.0, 1.0)

    def compute_market_impact(
        self, position_size: float, avg_volume: float = 100.0
    ) -> float:
        """Compute market impact slippage.

        Model: impact = coefficient * sqrt(size / volume)

        Args:
            position_size: Position size in dollars
            avg_volume: Average volume in same units

        Returns:
            Negative PnL adjustment (bps)
        """
        if not self.config.model_market_impact or avg_volume == 0:
            return 0.0

        sqrt_ratio = np.sqrt(position_size / avg_volume)
        impact_bps = self.config.impact_coefficient * sqrt_ratio
        return impact_bps

    def compute_edge_decay(self, day: int) -> float:
        """Compute time-varying edge decay.

        Model: decay = exp(-t / half_life)

        Args:
            day: Current day

        Returns:
            Edge multiplier [0, 1]
        """
        if not self.config.model_edge_decay:
            return 1.0

        half_life = self.config.edge_decay_half_life_days
        decay = np.exp(-day / half_life)
        return np.clip(decay, 0.1, 1.0)  # Don't decay below 10% edge

    def compute_liquidity_limit(self) -> float:
        """Compute maximum position size due to liquidity.

        Model: max_fill = depth * participation_rate

        Returns:
            Maximum position size in dollars
        """
        if not self.config.model_liquidity:
            return float("inf")

        max_fill = (
            self.config.avg_order_book_depth * self.config.participation_rate
        )
        return max(max_fill, 1.0)

    def get_capital_injection(self, week: int) -> float:
        """Get capital injection for given week.

        Args:
            week: Week number (0-indexed)

        Returns:
            Capital injected this week
        """
        return self.config.capital_injection_weekly

    def run_single_path(self) -> dict:
        """Run a single simulation path.

        Returns:
            Dictionary with path results and timeseries data
        """
        # Initialize
        capital = self.config.starting_capital
        peak_capital = capital
        daily_capitals = [capital]
        daily_regimes = []
        trade_history = []
        losing_streak = 0
        total_days = int(self.config.weeks * 7)
        daily_infra = self.config.infra_cost_monthly / 30.0

        # Pre-compute edge decay factors for all days
        edge_decay_factors = np.array(
            [self.compute_edge_decay(day) for day in range(total_days)]
        )

        for day in range(total_days):
            # Update regime
            if self.regime_model:
                regime = self.regime_model.step(day)
                daily_regimes.append(regime)
            else:
                daily_regimes.append("static")

            # Capital injection (weekly)
            if day > 0 and day % 7 == 0:
                capital += self.get_capital_injection(day // 7)

            # Infrastructure cost
            capital -= daily_infra
            capital = max(0, capital)

            if capital <= 0:
                # Capital ruin
                for _ in range(self.config.trades_per_day):
                    daily_capitals.append(0)
                continue

            # Execute trades for this day
            for trade_idx in range(self.config.trades_per_day):
                if capital <= 0:
                    break

                # Select empirical trade
                trade = self.empirical_trades[
                    np.random.randint(0, len(self.empirical_trades))
                ]

                # Adjust win rate for regime
                base_win_rate = (
                    1.0 if trade["won"] else 0.0
                )  # Use realized outcome
                regime_adjusted_rate = self.get_regime_adjusted_win_rate(
                    self.empirical_win_rate
                )

                # Get rolling win rate and losing streak
                rolling_wr = self.get_rolling_win_rate(
                    trade_history, self.config.kelly_lookback_trades
                )
                losing_streak = (
                    losing_streak + 1 if len(trade_history) == 0 or not trade_history[-1].get("won") else 0
                )

                # Compute position size
                if self.config.use_kelly:
                    kelly_f = trade.get("kelly_f", 0.01)
                    if kelly_f <= 0:
                        continue

                    kelly_mult = self.compute_dynamic_kelly_multiplier(
                        rolling_wr, losing_streak
                    )
                    raw_size = kelly_f * kelly_mult * capital

                else:
                    raw_size = capital * 0.05  # 5% per trade flat

                # Apply drawdown scaling
                dd_scale = self.compute_drawdown_scaling(capital, peak_capital)
                raw_size *= dd_scale

                # Apply liquidity constraint
                liquidity_limit = self.compute_liquidity_limit()
                raw_size = min(raw_size, liquidity_limit)

                # Enforce position bounds
                size = np.clip(
                    raw_size, self.config.position_min, self.config.position_max
                )
                if size < self.config.position_min:
                    continue

                # Get outcome with fat tails
                if self.config.use_fat_tails:
                    tail_perturbation = (
                        self.fat_tail_dist.sample(1)[0]
                        * regime_adjusted_rate
                        * 0.1
                    )
                else:
                    tail_perturbation = 0

                # Base PnL
                base_pnl_pct = trade["pnl_pct"]

                # Apply edge decay
                edge_mult = edge_decay_factors[day]
                effective_pnl_pct = base_pnl_pct * edge_mult

                # Apply market impact
                impact = self.compute_market_impact(size, avg_volume=200.0)
                effective_pnl_pct -= impact / 10000.0  # Convert bps to fraction

                # Apply fat-tail perturbation
                effective_pnl_pct += tail_perturbation

                # Execute trade
                pnl = size * effective_pnl_pct
                capital += pnl

                # Record trade
                trade_record = {
                    "pnl": pnl,
                    "pnl_pct": effective_pnl_pct,
                    "size": size,
                    "won": pnl > 0,
                    "day": day,
                    "regime": daily_regimes[-1],
                }
                trade_history.append(trade_record)

                # Update losing streak
                if pnl <= 0:
                    losing_streak += 1
                else:
                    losing_streak = 0

            # Record daily capital
            capital = max(0, capital)
            daily_capitals.append(capital)
            peak_capital = max(peak_capital, capital)

        return {
            "final_capital": capital,
            "daily_capitals": daily_capitals,
            "daily_regimes": daily_regimes,
            "peak_capital": peak_capital,
            "trade_history": trade_history,
        }

    def run_simulation(self) -> dict:
        """Run full Monte Carlo simulation.

        Returns:
            Aggregated results dictionary with statistics
        """
        final_capitals = []
        max_drawdowns = []
        daily_equity_paths = []  # For confidence bands
        ruin_count = 0
        dd_50_count = 0
        dd_40_count = 0
        total_trades_count = 0
        avg_win_rates = []

        for path_idx in range(self.config.num_paths):
            path_results = self.run_single_path()

            final_capital = path_results["final_capital"]
            daily_capitals = path_results["daily_capitals"]

            # Compute drawdown
            peak = self.config.starting_capital
            max_dd = 0.0
            for cap in daily_capitals:
                peak = max(peak, cap)
                if peak > 0:
                    dd = (peak - cap) / peak
                    max_dd = max(max_dd, dd)

            final_capitals.append(final_capital)
            max_drawdowns.append(max_dd)

            if final_capital <= 0:
                ruin_count += 1
            if max_dd >= 0.50:
                dd_50_count += 1
            if max_dd >= 0.40:
                dd_40_count += 1

            # Compute path win rate
            trades = path_results["trade_history"]
            if trades:
                path_win_rate = sum(1 for t in trades if t["won"]) / len(trades)
                avg_win_rates.append(path_win_rate)
                total_trades_count += len(trades)

            # Store for confidence bands
            daily_equity_paths.append(daily_capitals)

        # Compute percentiles
        final_capitals_sorted = sorted(final_capitals)
        max_drawdowns_sorted = sorted(max_drawdowns)

        def percentile(data: list, p: float) -> float:
            if len(data) == 0:
                return 0.0
            idx = int(len(data) * p / 100)
            return float(data[min(idx, len(data) - 1)])

        # Compute confidence bands
        confidence_bands = self._compute_confidence_bands(daily_equity_paths)

        # Compute returns
        final_mean = np.mean(final_capitals)
        final_median = percentile(final_capitals_sorted, 50)
        final_p5 = percentile(final_capitals_sorted, 5)
        final_p95 = percentile(final_capitals_sorted, 95)

        annual_return_p5 = (
            (final_p5 - self.config.starting_capital) / self.config.starting_capital
            * 100
        )
        annual_return_median = (
            (final_median - self.config.starting_capital)
            / self.config.starting_capital
            * 100
        )
        annual_return_p95 = (
            (final_p95 - self.config.starting_capital) / self.config.starting_capital
            * 100
        )

        results = {
            "parameters": {
                "starting_capital": self.config.starting_capital,
                "weeks": self.config.weeks,
                "trades_per_day": self.config.trades_per_day,
                "capital_injection_weekly": self.config.capital_injection_weekly,
                "num_paths": self.config.num_paths,
                "use_kelly": self.config.use_kelly,
                "empirical_trades_loaded": len(self.empirical_trades),
                "empirical_win_rate": float(self.empirical_win_rate),
                "enable_regimes": self.config.enable_regimes,
                "use_fat_tails": self.config.use_fat_tails,
                "model_edge_decay": self.config.model_edge_decay,
                "model_market_impact": self.config.model_market_impact,
                "model_liquidity": self.config.model_liquidity,
                "dynamic_kelly": self.config.dynamic_kelly,
            },
            "final_capital": {
                "mean": float(final_mean),
                "median": float(final_median),
                "p5": float(final_p5),
                "p10": float(percentile(final_capitals_sorted, 10)),
                "p25": float(percentile(final_capitals_sorted, 25)),
                "p75": float(percentile(final_capitals_sorted, 75)),
                "p90": float(percentile(final_capitals_sorted, 90)),
                "p95": float(final_p95),
                "min": float(final_capitals_sorted[0]),
                "max": float(final_capitals_sorted[-1]),
            },
            "annual_return_pct": {
                "p5": float(annual_return_p5),
                "median": float(annual_return_median),
                "p95": float(annual_return_p95),
            },
            "risk": {
                "probability_ruin": float(ruin_count / self.config.num_paths),
                "probability_dd_40pct": float(dd_40_count / self.config.num_paths),
                "probability_dd_50pct": float(dd_50_count / self.config.num_paths),
                "avg_max_drawdown": float(np.mean(max_drawdowns)),
                "median_max_drawdown": float(
                    percentile(max_drawdowns_sorted, 50)
                ),
                "p95_max_drawdown": float(
                    percentile(max_drawdowns_sorted, 95)
                ),
            },
            "trading_stats": {
                "total_trades": int(total_trades_count),
                "avg_trades_per_path": float(
                    total_trades_count / max(self.config.num_paths, 1)
                ),
                "avg_win_rate_across_paths": float(
                    np.mean(avg_win_rates) if avg_win_rates else 0
                ),
            },
            "confidence_bands": confidence_bands,
        }

        return results

    def _compute_confidence_bands(self, daily_equity_paths: list) -> dict:
        """Compute confidence bands at each day.

        Args:
            daily_equity_paths: List of daily capital arrays

        Returns:
            Dictionary with percentile curves
        """
        if not daily_equity_paths:
            return {}

        # Pad to same length
        max_len = max(len(p) for p in daily_equity_paths)
        padded_paths = []
        for path in daily_equity_paths:
            if len(path) < max_len:
                # Forward fill missing days
                padded = path + [path[-1]] * (max_len - len(path))
            else:
                padded = path
            padded_paths.append(padded)

        # Compute percentiles day by day
        percentile_arrays = {}
        for p in [5, 10, 25, 50, 75, 90, 95]:
            percentile_arrays[f"p{p}"] = []
            for day_idx in range(max_len):
                day_values = [path[day_idx] for path in padded_paths]
                pct = np.percentile(day_values, p)
                percentile_arrays[f"p{p}"].append(float(pct))

        return {
            "days": list(range(max_len)),
            "p5": percentile_arrays["p5"][:100],  # Sample first 100 days
            "p10": percentile_arrays["p10"][:100],
            "p25": percentile_arrays["p25"][:100],
            "p50": percentile_arrays["p50"][:100],
            "p75": percentile_arrays["p75"][:100],
            "p90": percentile_arrays["p90"][:100],
            "p95": percentile_arrays["p95"][:100],
        }


def run_advanced_simulation(
    config: SimulationConfig | None = None,
) -> dict:
    """Run advanced Monte Carlo simulation.

    Args:
        config: SimulationConfig object (uses defaults if None)

    Returns:
        Results dictionary
    """
    if config is None:
        config = SimulationConfig()

    trades = load_empirical_trades()
    print(f"Loaded {len(trades)} empirical trades")
    print(f"  Empirical win rate: {sum(1 for t in trades if t['won']) / len(trades):.1%}")

    engine = AdvancedMonteCarloEngine(trades, config)
    results = engine.run_simulation()

    return results


def print_advanced_report(results: dict) -> None:
    """Print formatted advanced simulation report.

    Args:
        results: Results dictionary from run_advanced_simulation()
    """
    p = results["parameters"]
    fc = results["final_capital"]
    risk = results["risk"]
    ret = results["annual_return_pct"]
    trades = results["trading_stats"]

    print("\n" + "=" * 80)
    print("  ADVANCED MONTE CARLO SIMULATION REPORT")
    print("=" * 80)

    print(f"\n  SIMULATION PARAMETERS:")
    print(f"    Starting capital: ${p['starting_capital']:.2f}")
    print(f"    Weekly injection: ${p['capital_injection_weekly']:.2f}")
    print(f"    Duration: {p['weeks']} weeks | Trades/day: {p['trades_per_day']}")
    print(f"    Paths: {p['num_paths']:,}")
    print(f"    Empirical win rate: {p['empirical_win_rate']:.1%}")

    print(f"\n  ADVANCED FEATURES ENABLED:")
    print(f"    Regime switching: {p['enable_regimes']}")
    print(f"    Fat tails (Student-t): {p['use_fat_tails']}")
    print(f"    Edge decay: {p['model_edge_decay']}")
    print(f"    Market impact: {p['model_market_impact']}")
    print(f"    Liquidity constraints: {p['model_liquidity']}")
    print(f"    Dynamic Kelly: {p['dynamic_kelly']}")

    print(f"\n  FINAL CAPITAL DISTRIBUTION:")
    print(f"    5th percentile:   ${fc['p5']:>12.2f}  (worst reasonable case)")
    print(f"    10th percentile:  ${fc['p10']:>12.2f}")
    print(f"    25th percentile:  ${fc['p25']:>12.2f}")
    print(f"    Median (p50):     ${fc['p50']:>12.2f}")
    print(f"    Mean:             ${fc['mean']:>12.2f}")
    print(f"    75th percentile:  ${fc['p75']:>12.2f}")
    print(f"    90th percentile:  ${fc['p90']:>12.2f}")
    print(f"    95th percentile:  ${fc['p95']:>12.2f}  (best reasonable case)")
    print(f"    Range: ${fc['min']:.2f} to ${fc['max']:.2f}")

    print(f"\n  ANNUALIZED RETURN:")
    print(f"    5th percentile:   {ret['p5']:>+8.1f}%")
    print(f"    Median:           {ret['median']:>+8.1f}%")
    print(f"    95th percentile:  {ret['p95']:>+8.1f}%")

    print(f"\n  RISK METRICS:")
    print(f"    Probability of ruin (0%): {risk['probability_ruin']:.1%}")
    print(f"    Probability of -40% DD:   {risk['probability_dd_40pct']:.1%}")
    print(f"    Probability of -50% DD:   {risk['probability_dd_50pct']:.1%}")
    print(f"    Average max drawdown:     {risk['avg_max_drawdown']:.1%}")
    print(f"    Median max drawdown:      {risk['median_max_drawdown']:.1%}")
    print(f"    95th pct max drawdown:    {risk['p95_max_drawdown']:.1%}")

    print(f"\n  TRADING STATISTICS:")
    print(f"    Total trades (all paths): {trades['total_trades']:,}")
    print(f"    Avg trades per path:      {trades['avg_trades_per_path']:.0f}")
    print(f"    Avg realized win rate:    {trades['avg_win_rate_across_paths']:.1%}")

    print("=" * 80)


def run_scenario_analysis() -> dict:
    """Run multiple scenario analyses.

    Returns:
        Dictionary with results for each scenario
    """
    scenarios = {
        "conservative": SimulationConfig(
            starting_capital=75.0,
            capital_injection_weekly=1.0,
            weeks=52,
            kelly_base_multiplier=0.15,
            kelly_reduction_on_losing_streak=0.6,
            max_drawdown_allowed=0.30,
            edge_decay_half_life_days=120.0,
        ),
        "moderate": SimulationConfig(
            starting_capital=75.0,
            capital_injection_weekly=1.0,
            weeks=52,
            kelly_base_multiplier=0.25,
            kelly_reduction_on_losing_streak=0.5,
            max_drawdown_allowed=0.40,
            edge_decay_half_life_days=180.0,
        ),
        "aggressive": SimulationConfig(
            starting_capital=75.0,
            capital_injection_weekly=1.0,
            weeks=52,
            kelly_base_multiplier=0.40,
            kelly_reduction_on_losing_streak=0.4,
            max_drawdown_allowed=0.50,
            edge_decay_half_life_days=240.0,
        ),
        "crisis": SimulationConfig(
            starting_capital=75.0,
            capital_injection_weekly=1.0,
            weeks=52,
            kelly_base_multiplier=0.25,
            kelly_reduction_on_losing_streak=0.5,
            max_drawdown_allowed=0.40,
            enable_regimes=True,  # Extra regime stress
            regime_transition_days=14,  # Faster regime changes
        ),
    }

    scenario_results = {}

    for scenario_name, config in scenarios.items():
        print(f"\n>>> Running {scenario_name.upper()} scenario...")
        results = run_advanced_simulation(config)
        scenario_results[scenario_name] = results
        print_advanced_report(results)

    return scenario_results


if __name__ == "__main__":
    # Run scenario analysis
    print("ADVANCED MONTE CARLO SIMULATION ENGINE")
    print("=" * 80)

    scenario_results = run_scenario_analysis()

    # Save results
    output_path = os.path.join(DATA_DIR, "monte_carlo_advanced_results.json")
    with open(output_path, "w") as f:
        json.dump(scenario_results, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")

    # Summary comparison
    print("\n" + "=" * 80)
    print("  SCENARIO COMPARISON")
    print("=" * 80)

    print(f"\n{'Scenario':<15} {'Median Final':<15} {'P95 Final':<15} {'Ruin Risk':<12} {'Max DD (p95)':<12}")
    print("-" * 70)

    for scenario_name, results in scenario_results.items():
        fc = results["final_capital"]
        risk = results["risk"]
        print(
            f"{scenario_name:<15} ${fc['median']:<14.2f} ${fc['p95']:<14.2f} "
            f"{risk['probability_ruin']:<11.1%} {risk['p95_max_drawdown']:<11.1%}"
        )

    print("=" * 80)
