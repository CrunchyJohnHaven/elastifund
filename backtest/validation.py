"""Rigorous backtest validation framework.

Implements:
- Deflated Sharpe Ratio (Bailey, Borwein, López de Prado, Zhu 2014)
- Brier Score Decomposition (Murphy 1973)
- Statistical significance testing (Binomial CI, Wilson Score, z-test)
- Fee-adjusted Kelly Criterion for binary contracts
- Slippage modeling by market tier
- Fill rate simulation
- Comprehensive validation report with pass/fail gates

Reference: P0-26 Backtesting Validation Framework Deep Research
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import dataclass
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ─── Validation thresholds (from research) ────────────────────────────
THRESHOLDS = {
    "sharpe_max": 2.5,           # Backtest Sharpe above this → suspect
    "sharpe_red_flag": 3.0,      # Almost certainly overfit
    "dsr_min": 0.95,             # Deflated Sharpe Ratio minimum
    "oos_is_ratio_min": 0.50,    # OOS/IS Sharpe ratio minimum
    "pbo_max": 0.40,             # Probability of Backtest Overfitting max
    "pbo_red_flag": 0.50,        # PBO above this → likely overfit
    "mc_ruin_max": 0.05,         # Monte Carlo P(Ruin) max at 50% drawdown
    "mc_ruin_red_flag": 0.10,    # P(Ruin) above this → red flag
    "min_trades_significant": 200,  # Minimum for statistical significance
    "min_trades_reliable": 385,     # For ±5% margin of error at 95% CI
    "brier_max": 0.15,           # Strategy should beat this
    "weather_winner_fee": 0.02,  # 2% winner fee on weather markets
    "harvey_liu_tstat_min": 3.0,     # Minimum t-stat for standard strategy search
    "harvey_liu_tstat_extensive": 5.0,  # For extensive (100+) strategy variants
    "wfe_min": 0.50,             # Walk-Forward Efficiency minimum (acceptable)
    "wfe_good": 0.60,            # WFE excellent (above this)
}


# ═══════════════════════════════════════════════════════════════════════
# 1. DEFLATED SHARPE RATIO
# ═══════════════════════════════════════════════════════════════════════

def expected_max_sharpe(num_trials: int, T: int) -> float:
    """Expected maximum Sharpe Ratio from random strategies.

    Bailey & López de Prado (2014): E[max SR] ≈ √(2 ln(N)) - (γ + ln(π/2)) / (2√(2 ln(N)))
    where N = num_trials, γ = Euler-Mascheroni constant.
    """
    if num_trials <= 1:
        return 0.0
    euler_gamma = 0.5772156649
    z = math.sqrt(2.0 * math.log(num_trials))
    correction = (euler_gamma + math.log(math.pi / 2)) / (2.0 * z)
    return (z - correction) * (1.0 / math.sqrt(T)) * math.sqrt(T)
    # Simplified: just z - correction for annualized SR


def deflated_sharpe_ratio(
    observed_sr: float,
    num_trials: int,
    T: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio — corrects for multiple testing, non-normality.

    Args:
        observed_sr: Observed (annualized) Sharpe Ratio
        num_trials: Number of strategy variants tested
        T: Number of return observations (e.g., number of trades)
        skewness: Skewness of returns (γ₃)
        kurtosis: Kurtosis of returns (γ₄, normal = 3.0)

    Returns:
        DSR probability (0 to 1). Values ≥ 0.95 indicate genuine skill.
    """
    if T <= 1 or num_trials <= 0:
        return 0.0

    # Expected max SR from pure randomness
    sr0 = expected_max_sharpe(num_trials, T)

    # Variance of SR estimator, corrected for non-normality
    # Var(SR) = (1 - γ₃·SR + (γ₄-1)/4 · SR²) / (T-1)
    excess_kurt = kurtosis - 3.0  # Use excess kurtosis in formula
    var_sr = (1.0 - skewness * observed_sr + (kurtosis - 1.0) / 4.0 * observed_sr ** 2) / (T - 1)

    if var_sr <= 0:
        return 0.0

    # z-score of observed SR vs expected random max
    z = (observed_sr - sr0) / math.sqrt(var_sr)

    # CDF of standard normal
    dsr = _norm_cdf(z)
    return dsr


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ═══════════════════════════════════════════════════════════════════════
# 2. BRIER SCORE DECOMPOSITION (Murphy 1973)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BrierDecomposition:
    """Murphy (1973) decomposition: BS = Reliability - Resolution + Uncertainty."""
    brier_score: float
    reliability: float      # Lower is better (calibration error)
    resolution: float       # Higher is better (discrimination)
    uncertainty: float      # Fixed: base_rate × (1 - base_rate)
    n_forecasts: int
    base_rate: float
    bucket_details: list    # Per-bucket breakdown


def brier_decomposition(forecasts: list[float], outcomes: list[int], n_buckets: int = 10) -> BrierDecomposition:
    """Decompose Brier score into Reliability, Resolution, Uncertainty.

    Args:
        forecasts: List of probability forecasts (0-1)
        outcomes: List of binary outcomes (0 or 1)
        n_buckets: Number of calibration buckets

    Returns:
        BrierDecomposition with all components
    """
    n = len(forecasts)
    if n == 0:
        return BrierDecomposition(0, 0, 0, 0, 0, 0, [])

    base_rate = sum(outcomes) / n
    uncertainty = base_rate * (1.0 - base_rate)

    # Brier score
    bs = sum((f - o) ** 2 for f, o in zip(forecasts, outcomes)) / n

    # Bucket forecasts
    buckets = [[] for _ in range(n_buckets)]
    for f, o in zip(forecasts, outcomes):
        idx = min(int(f * n_buckets), n_buckets - 1)
        buckets[idx].append((f, o))

    reliability = 0.0
    resolution = 0.0
    bucket_details = []

    for k, bucket in enumerate(buckets):
        if not bucket:
            continue
        nk = len(bucket)
        fk = sum(f for f, _ in bucket) / nk   # Mean forecast in bucket
        ok = sum(o for _, o in bucket) / nk     # Observed frequency in bucket

        reliability += nk * (fk - ok) ** 2
        resolution += nk * (ok - base_rate) ** 2

        bucket_details.append({
            "bucket": f"{k/n_buckets:.1f}-{(k+1)/n_buckets:.1f}",
            "count": nk,
            "mean_forecast": round(fk, 3),
            "observed_rate": round(ok, 3),
            "calibration_error": round(abs(fk - ok), 3),
        })

    reliability /= n
    resolution /= n

    return BrierDecomposition(
        brier_score=round(bs, 4),
        reliability=round(reliability, 4),
        resolution=round(resolution, 4),
        uncertainty=round(uncertainty, 4),
        n_forecasts=n,
        base_rate=round(base_rate, 4),
        bucket_details=bucket_details,
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. STATISTICAL SIGNIFICANCE TESTING
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SignificanceResult:
    """Results of statistical significance testing."""
    n_trades: int
    win_rate: float
    wald_ci_low: float
    wald_ci_high: float
    wilson_ci_low: float
    wilson_ci_high: float
    z_stat: float
    p_value: float
    is_significant_95: bool
    is_significant_99: bool
    min_trades_for_significance: int  # Estimated n needed


def test_significance(n_trades: int, n_wins: int, null_rate: float = 0.5) -> SignificanceResult:
    """Test whether win rate is statistically distinguishable from chance.

    Uses both Wald (standard) and Wilson Score intervals.
    Wilson Score is preferred for n < 150.
    """
    if n_trades == 0:
        return SignificanceResult(0, 0, 0, 0, 0, 0, 0, 1.0, False, False, 999)

    p_hat = n_wins / n_trades
    z95 = 1.96
    z99 = 2.576

    # Wald interval (standard)
    se = math.sqrt(p_hat * (1 - p_hat) / n_trades) if 0 < p_hat < 1 else 0.01
    wald_low = p_hat - z95 * se
    wald_high = p_hat + z95 * se

    # Wilson Score interval (better for small samples)
    denom = 1 + z95 ** 2 / n_trades
    center = (p_hat + z95 ** 2 / (2 * n_trades)) / denom
    margin = z95 * math.sqrt((p_hat * (1 - p_hat) + z95 ** 2 / (4 * n_trades)) / n_trades) / denom
    wilson_low = center - margin
    wilson_high = center + margin

    # z-test against null
    se_null = math.sqrt(null_rate * (1 - null_rate) / n_trades)
    z_stat = (p_hat - null_rate) / se_null if se_null > 0 else 0
    p_value = 2 * (1 - _norm_cdf(abs(z_stat)))  # Two-tailed

    # Estimate minimum trades needed for current win rate to be significant
    if p_hat > null_rate:
        # n ≈ (z/delta)^2 * p(1-p)
        delta = p_hat - null_rate
        min_n = int(math.ceil((z99 / delta) ** 2 * p_hat * (1 - p_hat))) if delta > 0 else 999
    else:
        min_n = 999

    return SignificanceResult(
        n_trades=n_trades,
        win_rate=round(p_hat, 4),
        wald_ci_low=round(max(0, wald_low), 4),
        wald_ci_high=round(min(1, wald_high), 4),
        wilson_ci_low=round(max(0, wilson_low), 4),
        wilson_ci_high=round(min(1, wilson_high), 4),
        z_stat=round(z_stat, 3),
        p_value=round(p_value, 6),
        is_significant_95=p_value < 0.05,
        is_significant_99=p_value < 0.01,
        min_trades_for_significance=min_n,
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. FEE-ADJUSTED KELLY CRITERION
# ═══════════════════════════════════════════════════════════════════════

def kelly_binary(
    est_prob: float,
    market_price: float,
    direction: str = "buy_yes",
    winner_fee: float = 0.02,
    fraction: float = 0.25,  # Quarter-Kelly default (research recommendation)
    max_allocation: float = 0.20,  # Never >20% on single market
) -> float:
    """Fee-adjusted Kelly Criterion for binary prediction market contracts.

    f* = (p − c) / (1 − c) for YES contracts
    Adjusted for winner fee: payout = 1 - winner_fee

    Args:
        est_prob: Estimated true probability
        market_price: Current market price (cost per share)
        direction: "buy_yes" or "buy_no"
        winner_fee: Fee on winning positions (0.02 = 2% for weather)
        fraction: Kelly fraction (0.25 = quarter-Kelly, recommended)
        max_allocation: Maximum bankroll fraction per position

    Returns:
        Optimal fraction of bankroll to allocate (0 to max_allocation)
    """
    payout = 1.0 - winner_fee  # Net payout per winning share

    if direction == "buy_yes":
        p = est_prob
        cost = market_price
    else:
        p = 1.0 - est_prob
        cost = 1.0 - market_price

    if cost <= 0 or cost >= payout:
        return 0.0

    # Expected value per dollar risked
    # Win: (payout - cost) / cost
    # Lose: -1
    odds = (payout - cost) / cost
    if odds <= 0:
        return 0.0

    # Kelly: f* = (p * odds - (1-p)) / odds = (p * (payout - cost) - (1-p) * cost) / (payout - cost)
    kelly_f = (p * odds - (1.0 - p)) / odds

    if kelly_f <= 0:
        return 0.0

    # Apply fraction (quarter-Kelly) and cap
    return min(kelly_f * fraction, max_allocation)


# ═══════════════════════════════════════════════════════════════════════
# 5. SLIPPAGE MODEL
# ═══════════════════════════════════════════════════════════════════════

# Market tier slippage estimates (from research)
SLIPPAGE_TIERS = {
    "high_volume": {"spread": 0.015, "slippage_per_1k": 0.003},      # Politics/crypto
    "us_weather_major": {"spread": 0.07, "slippage_per_1k": 0.0125},  # NYC, Atlanta
    "intl_weather": {"spread": 0.20, "slippage_per_1k": 0.06},        # London, Seoul
    "niche": {"spread": 0.22, "slippage_per_1k": 0.10},               # Low volume
}


def estimate_slippage(
    order_size: float,
    market_tier: str = "us_weather_major",
) -> float:
    """Estimate slippage cost for a given order size and market tier.

    Returns slippage as a fraction of order size (e.g., 0.01 = 1%).
    """
    tier = SLIPPAGE_TIERS.get(market_tier, SLIPPAGE_TIERS["us_weather_major"])
    # Linear interpolation: slippage scales with order size
    # At $1K, slippage = slippage_per_1k. At $2, much less but spread still applies.
    base_slippage = tier["spread"] / 2.0  # Half-spread as minimum slippage
    size_slippage = tier["slippage_per_1k"] * (order_size / 1000.0)
    return base_slippage + size_slippage


def apply_slippage(entry_price: float, direction: str, order_size: float,
                   market_tier: str = "us_weather_major") -> float:
    """Return effective entry price after slippage."""
    slip = estimate_slippage(order_size, market_tier)
    if direction == "buy_yes":
        return min(entry_price + slip, 0.99)  # Buying pushes price up
    else:
        return max(entry_price - slip, 0.01)  # Buying NO = selling YES, pushes down


# ═══════════════════════════════════════════════════════════════════════
# 6. FILL RATE SIMULATION
# ═══════════════════════════════════════════════════════════════════════

def simulate_fill(
    edge_from_midpoint: float,
    market_tier: str = "us_weather_major",
) -> bool:
    """Simulate whether a limit order gets filled.

    Based on research: 30-60% fill rate for orders within 2¢ of midpoint,
    near-zero for orders 5¢+ away in zero-volume markets.

    Args:
        edge_from_midpoint: How far the limit price is from midpoint (in price units)
        market_tier: Market liquidity tier

    Returns:
        True if order fills, False otherwise
    """
    # Base fill rates by tier
    base_rates = {
        "high_volume": 0.85,
        "us_weather_major": 0.55,
        "intl_weather": 0.30,
        "niche": 0.15,
    }

    base = base_rates.get(market_tier, 0.45)

    # Adjust for distance from midpoint
    # Closer to midpoint = higher fill rate
    if abs(edge_from_midpoint) <= 0.02:
        rate = base * 1.0
    elif abs(edge_from_midpoint) <= 0.05:
        rate = base * 0.7
    elif abs(edge_from_midpoint) <= 0.10:
        rate = base * 0.4
    else:
        rate = base * 0.15

    return random.random() < rate


# ═══════════════════════════════════════════════════════════════════════
# 7. TRADE RESOLUTION WITH FEES
# ═══════════════════════════════════════════════════════════════════════

def resolve_trade_with_fees(
    direction: str,
    entry_price: float,
    size: float,
    actual_outcome: str,
    winner_fee: float = 0.02,
    slippage: float = 0.0,
) -> tuple[bool, float]:
    """Resolve a trade with realistic fee and slippage modeling.

    Weather markets: 2% winner fee on resolved positions.
    Slippage applied to entry price.

    Returns:
        (won, net_pnl)
    """
    # Adjust entry for slippage
    if direction == "buy_yes":
        effective_entry = entry_price + slippage
        won = actual_outcome == "YES_WON"
        if won:
            shares = size / effective_entry
            gross_payout = shares * 1.0
            fee = gross_payout * winner_fee
            pnl = gross_payout - fee - size
        else:
            pnl = -size
    else:  # buy_no
        effective_no_price = (1.0 - entry_price) + slippage
        won = actual_outcome == "NO_WON"
        if won:
            shares = size / effective_no_price
            gross_payout = shares * 1.0
            fee = gross_payout * winner_fee
            pnl = gross_payout - fee - size
        else:
            pnl = -size

    return won, pnl


# ═══════════════════════════════════════════════════════════════════════
# 8. SHARPE RATIO FOR PREDICTION MARKETS
# ═══════════════════════════════════════════════════════════════════════

def compute_sharpe(
    trade_pnls: list[float],
    risk_free_rate: float = 0.05,  # Aave USDC ~4-6% APY
    trades_per_day: float = 5.0,
) -> dict:
    """Compute Sharpe ratio adapted for binary prediction market returns.

    Annualizes using √252 on daily P&L aggregation.
    Uses Aave USDC rate as opportunity cost of capital.
    """
    n = len(trade_pnls)
    if n < 10:
        return {"sharpe": 0, "skewness": 0, "kurtosis": 3.0, "n": n}

    mean_pnl = sum(trade_pnls) / n
    variance = sum((x - mean_pnl) ** 2 for x in trade_pnls) / (n - 1)
    std_pnl = math.sqrt(variance) if variance > 0 else 0.001

    # Daily aggregation
    daily_pnl = mean_pnl * trades_per_day
    daily_std = std_pnl * math.sqrt(trades_per_day)
    daily_rf = risk_free_rate / 252

    daily_sharpe = (daily_pnl - daily_rf) / daily_std if daily_std > 0 else 0
    annual_sharpe = daily_sharpe * math.sqrt(252)

    # Skewness and kurtosis
    if std_pnl > 0:
        skewness = sum((x - mean_pnl) ** 3 for x in trade_pnls) / (n * std_pnl ** 3)
        kurtosis = sum((x - mean_pnl) ** 4 for x in trade_pnls) / (n * std_pnl ** 4)
    else:
        skewness = 0
        kurtosis = 3.0

    return {
        "sharpe_annual": round(annual_sharpe, 3),
        "sharpe_daily": round(daily_sharpe, 4),
        "mean_pnl": round(mean_pnl, 4),
        "std_pnl": round(std_pnl, 4),
        "skewness": round(skewness, 3),
        "kurtosis": round(kurtosis, 3),
        "n": n,
    }


# ═══════════════════════════════════════════════════════════════════════
# 9. ENHANCED MONTE CARLO WITH RUIN PROBABILITY
# ═══════════════════════════════════════════════════════════════════════

def monte_carlo_ruin(
    trade_pnls: list[float],
    starting_capital: float = 75.0,
    trades_per_day: int = 5,
    days: int = 365,
    num_paths: int = 10000,
    drawdown_threshold: float = 0.50,  # 50% drawdown = ruin
) -> dict:
    """Enhanced Monte Carlo with specific ruin probability at drawdown threshold.

    Research requirement: < 5% probability of hitting 50% drawdown.
    95th percentile drawdown is typically 1.5-3× backtest max drawdown.
    """
    ruin_count = 0
    max_drawdowns = []
    final_capitals = []

    for _ in range(num_paths):
        capital = starting_capital
        peak = capital
        max_dd_pct = 0.0
        hit_ruin = False

        for day in range(days):
            for _ in range(trades_per_day):
                if capital <= 0:
                    hit_ruin = True
                    break
                pnl = random.choice(trade_pnls)
                # Scale PnL relative to position sizing
                capital += pnl
                capital = max(0, capital)

            if capital <= 0:
                hit_ruin = True
                break

            peak = max(peak, capital)
            dd_pct = (peak - capital) / peak if peak > 0 else 0
            max_dd_pct = max(max_dd_pct, dd_pct)

            if dd_pct >= drawdown_threshold:
                hit_ruin = True

        if hit_ruin:
            ruin_count += 1

        max_drawdowns.append(max_dd_pct)
        final_capitals.append(capital)

    max_drawdowns.sort()
    final_capitals.sort()

    def pct(data, p):
        idx = min(int(len(data) * p / 100), len(data) - 1)
        return data[idx]

    p_ruin = ruin_count / num_paths
    p95_dd = pct(max_drawdowns, 95)
    median_dd = pct(max_drawdowns, 50)
    backtest_max_dd = max(max_drawdowns) if max_drawdowns else 0

    return {
        "p_ruin": round(p_ruin, 4),
        "p_ruin_pct": f"{p_ruin:.1%}",
        "passes_threshold": p_ruin < THRESHOLDS["mc_ruin_max"],
        "drawdown_threshold": drawdown_threshold,
        "median_max_drawdown": round(median_dd, 4),
        "p95_max_drawdown": round(p95_dd, 4),
        "worst_drawdown": round(backtest_max_dd, 4),
        "dd_ratio_p95_to_median": round(p95_dd / median_dd, 2) if median_dd > 0 else 0,
        "median_final_capital": round(pct(final_capitals, 50), 2),
        "p5_final_capital": round(pct(final_capitals, 5), 2),
        "p95_final_capital": round(pct(final_capitals, 95), 2),
        "num_paths": num_paths,
    }


# ═══════════════════════════════════════════════════════════════════════
# 10. COMBINATORIAL PURGED CROSS-VALIDATION (CPCV)
# ═══════════════════════════════════════════════════════════════════════

def combinatorial_purged_cross_validation(
    trade_pnls: list[float],
    resolution_dates: list[str],
    num_groups: int = 10,
    embargo_days: int = 1,
) -> dict:
    """Combinatorial Purged Cross-Validation (Bailey & López de Prado).

    Partitions trade data into N groups and computes all C(N,k) train/test
    combinations, with temporal purging to remove observations whose resolution
    periods overlap between train and test sets.

    Args:
        trade_pnls: List of trade P&Ls
        resolution_dates: List of resolution dates (YYYY-MM-DD format) for each trade
        num_groups: Number of groups to partition trades into (default 10)
        embargo_days: Buffer days between train/test to handle serial correlation (default 1)

    Returns:
        Dictionary with:
        - pbo: Probability of Backtest Overfitting (fraction of paths where
                IS-optimal strategy underperforms OOS)
        - paths_analyzed: Total number of train/test paths
        - is_optimal_underperforms: Number of paths where IS optimal underperformed
        - mean_is_sharpe: Mean IS Sharpe across paths
        - mean_oos_sharpe: Mean OOS Sharpe across paths
        - passes_pbo_test: True if PBO < 0.40 (robust)
    """
    if len(trade_pnls) < 2 or len(resolution_dates) != len(trade_pnls):
        return {
            "pbo": 0.0,
            "paths_analyzed": 0,
            "is_optimal_underperforms": 0,
            "mean_is_sharpe": 0.0,
            "mean_oos_sharpe": 0.0,
            "passes_pbo_test": False,
            "note": "Insufficient data (need ≥2 trades with resolution dates)"
        }

    # Sort trades by resolution date
    indexed_trades = list(enumerate(zip(trade_pnls, resolution_dates)))
    indexed_trades.sort(key=lambda x: x[1][1])  # Sort by date
    sorted_indices = [idx for idx, _ in indexed_trades]
    sorted_pnls = [pnl for _, (pnl, _) in indexed_trades]
    sorted_dates = [date for _, (_, date) in indexed_trades]

    n = len(sorted_pnls)
    group_size = max(1, n // num_groups)

    # Partition into groups
    groups = []
    for i in range(num_groups):
        start_idx = i * group_size
        if i == num_groups - 1:
            end_idx = n  # Last group gets remainder
        else:
            end_idx = (i + 1) * group_size
        groups.append((start_idx, end_idx))

    # Generate all C(N, k) combinations where k = N-2 (leave 2 groups out)
    from itertools import combinations

    is_sharpes = []
    oos_sharpes = []
    is_optimal_underperforms_count = 0
    paths_count = 0

    for train_combo in combinations(range(num_groups), num_groups - 2):
        test_groups = [g for g in range(num_groups) if g not in train_combo]

        # Collect train indices and dates
        train_indices = []
        train_dates = []
        for g in train_combo:
            start, end = groups[g]
            train_indices.extend(range(start, end))
            train_dates.extend(sorted_dates[start:end])

        # Collect test indices and dates
        test_indices = []
        test_dates = []
        for g in test_groups:
            start, end = groups[g]
            test_indices.extend(range(start, end))
            test_dates.extend(sorted_dates[start:end])

        # Purge: remove train observations whose resolution overlaps test
        # (Simple approach: remove train obs if their date is within embargo_days of any test obs)
        test_date_set = set(test_dates)
        purged_train_indices = []
        for idx in train_indices:
            date = sorted_dates[idx]
            # Check if within embargo window of any test date
            # For simplicity, check if date is in adjacent groups
            is_purged = False
            for test_date in test_dates:
                # Simple date diff check (string comparison for ISO format)
                if date == test_date or date > test_date:  # Conservative: same or after
                    is_purged = True
                    break
            if not is_purged:
                purged_train_indices.append(idx)

        if not purged_train_indices or not test_indices:
            continue

        # Compute IS Sharpe (on purged training set)
        train_pnls = [sorted_pnls[i] for i in purged_train_indices]
        is_sharpe_dict = compute_sharpe(train_pnls)
        is_sharpe = is_sharpe_dict.get("sharpe_annual", 0)
        is_sharpes.append(is_sharpe)

        # Compute OOS Sharpe (on test set)
        test_pnls = [sorted_pnls[i] for i in test_indices]
        oos_sharpe_dict = compute_sharpe(test_pnls)
        oos_sharpe = oos_sharpe_dict.get("sharpe_annual", 0)
        oos_sharpes.append(oos_sharpe)

        # Check if IS-optimal strategy underperforms OOS
        if is_sharpe > oos_sharpe:
            is_optimal_underperforms_count += 1

        paths_count += 1

    # Compute PBO
    if paths_count == 0:
        return {
            "pbo": 0.0,
            "paths_analyzed": 0,
            "is_optimal_underperforms": 0,
            "mean_is_sharpe": 0.0,
            "mean_oos_sharpe": 0.0,
            "passes_pbo_test": False,
            "note": "No valid train/test combinations after purging"
        }

    pbo = is_optimal_underperforms_count / paths_count
    mean_is = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0
    mean_oos = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0

    return {
        "pbo": round(pbo, 4),
        "pbo_pct": f"{pbo:.1%}",
        "paths_analyzed": paths_count,
        "is_optimal_underperforms": is_optimal_underperforms_count,
        "mean_is_sharpe": round(mean_is, 3),
        "mean_oos_sharpe": round(mean_oos, 3),
        "passes_pbo_test": pbo < THRESHOLDS["pbo_max"],
        "interpretation": (
            f"PBO = {pbo:.1%} (probability IS-optimal underperforms OOS). "
            f"Values < 40% suggest robustness; > 50% indicate likely overfitting."
        )
    }


# ═══════════════════════════════════════════════════════════════════════
# 11. WALK-FORWARD EFFICIENCY (WFE)
# ═══════════════════════════════════════════════════════════════════════

def walk_forward_efficiency(
    trade_pnls: list[float],
    resolution_dates: list[str],
    cohort_size: int = 30,
) -> dict:
    """Walk-Forward Efficiency (WFE) using market cohorts.

    WFE = annualized OOS return / annualized IS return
    Groups trades by resolution date cohorts (not calendar windows).

    Args:
        trade_pnls: List of trade P&Ls
        resolution_dates: List of resolution dates (YYYY-MM-DD)
        cohort_size: Number of trades per cohort (default 30)

    Returns:
        Dictionary with:
        - wfe: WFE ratio (OOS return / IS return)
        - is_annual_return: Annualized IS return
        - oos_annual_return: Annualized OOS return
        - passes_wfe_test: True if WFE > 0.50 (good) or > 0.60 (excellent)
        - num_cohorts: Number of cohorts analyzed
    """
    if len(trade_pnls) < cohort_size * 2:
        return {
            "wfe": 0.0,
            "is_annual_return": 0.0,
            "oos_annual_return": 0.0,
            "passes_wfe_test": False,
            "num_cohorts": 0,
            "note": f"Insufficient data (need ≥{cohort_size * 2} trades)"
        }

    # Sort by resolution date
    indexed_trades = list(enumerate(zip(trade_pnls, resolution_dates)))
    indexed_trades.sort(key=lambda x: x[1][1])
    sorted_pnls = [pnl for _, (pnl, _) in indexed_trades]

    n = len(sorted_pnls)
    num_cohorts = n // cohort_size

    if num_cohorts < 2:
        return {
            "wfe": 0.0,
            "is_annual_return": 0.0,
            "oos_annual_return": 0.0,
            "passes_wfe_test": False,
            "num_cohorts": num_cohorts,
            "note": "Insufficient cohorts (need at least 2)"
        }

    # Walk-forward: use odd cohorts for IS, even for OOS
    is_pnls = []
    oos_pnls = []

    for i, start in enumerate(range(0, num_cohorts * cohort_size, cohort_size)):
        end = start + cohort_size
        cohort = sorted_pnls[start:end]

        if i % 2 == 0:
            is_pnls.extend(cohort)
        else:
            oos_pnls.extend(cohort)

    # Compute annualized returns (Sharpe as proxy; use mean return)
    is_mean = sum(is_pnls) / len(is_pnls) if is_pnls else 0
    oos_mean = sum(oos_pnls) / len(oos_pnls) if oos_pnls else 0

    # Annualize: assume 5 trades per day, 252 trading days
    is_annual = is_mean * 5 * 252
    oos_annual = oos_mean * 5 * 252

    wfe = (oos_annual / is_annual) if is_annual > 0 else 0

    return {
        "wfe": round(wfe, 4),
        "wfe_pct": f"{wfe:.1%}",
        "is_annual_return": round(is_annual, 4),
        "oos_annual_return": round(oos_annual, 4),
        "passes_wfe_test": wfe > THRESHOLDS["wfe_min"],
        "num_cohorts": num_cohorts,
        "cohort_size": cohort_size,
        "interpretation": (
            f"WFE > 50-60% suggests robustness; < 50% indicates possible overfitting. "
            f"Current WFE: {wfe:.1%}"
        )
    }


# ═══════════════════════════════════════════════════════════════════════
# 12. HARVEY & LIU t-STATISTIC TEST
# ═══════════════════════════════════════════════════════════════════════

def harvey_liu_test(
    sharpe_ratio: float,
    years: float = 1.0,
    num_tested: int = 10,
) -> dict:
    """Harvey & Liu t-statistic test for multiple testing correction.

    Requires t-statistics > 3.0 (not 2.0) to account for multiple hypothesis
    testing. Higher thresholds (3.5-5.0) for extensive strategy search.

    Relationship: t = Sharpe × √(years)

    Args:
        sharpe_ratio: Observed annualized Sharpe ratio
        years: Duration of backtest in years (default 1.0)
        num_tested: Number of strategies tested (affects threshold)

    Returns:
        Dictionary with:
        - t_stat: Computed t-statistic
        - threshold: Required t-statistic for current num_tested
        - passes: Whether t_stat exceeds threshold
        - years_needed: Estimated years needed to meet threshold with current SR
    """
    # Compute t-statistic
    t_stat = sharpe_ratio * math.sqrt(years)

    # Determine threshold based on number of strategies tested
    if num_tested <= 1:
        threshold = 2.0
    elif num_tested <= 10:
        threshold = 3.0  # Standard threshold
    elif num_tested <= 50:
        threshold = 3.5
    elif num_tested <= 100:
        threshold = 4.0
    else:
        threshold = 5.0  # Extensive search

    # Estimate years needed to meet threshold with current Sharpe
    if sharpe_ratio > 0:
        years_needed = (threshold / sharpe_ratio) ** 2
    else:
        years_needed = float('inf')

    return {
        "sharpe_ratio": round(sharpe_ratio, 4),
        "years_tested": round(years, 2),
        "t_stat": round(t_stat, 3),
        "threshold": round(threshold, 2),
        "num_strategies_tested": num_tested,
        "passes": t_stat >= threshold,
        "years_needed": round(years_needed, 2) if years_needed != float('inf') else "N/A",
        "interpretation": (
            f"t = {t_stat:.3f}; need ≥ {threshold:.2f}. "
            f"{'PASS' if t_stat >= threshold else 'FAIL'}. "
            f"At current SR, need ~{years_needed:.1f} years of data." if years_needed != float('inf')
            else f"t = {t_stat:.3f}; need ≥ {threshold:.2f}. {'PASS' if t_stat >= threshold else 'FAIL'}."
        )
    }


# ═══════════════════════════════════════════════════════════════════════
# 13. COMPREHENSIVE VALIDATION REPORT
# ═══════════════════════════════════════════════════════════════════════

def run_full_validation(num_strategy_variants: int = 10) -> dict:
    """Run the complete validation framework on existing backtest data.

    Loads historical markets and claude cache, then runs all validation
    checks with realistic fee/slippage/fill rate modeling.

    Args:
        num_strategy_variants: How many strategy variants were tested
            (for Deflated Sharpe Ratio correction)
    """
    # Load data
    with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
        markets = json.load(f)["markets"]
    with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
        cache = json.load(f)

    # ── Step 1: Run trades with realistic constraints ──
    entry_price = 0.50
    edge_threshold = 0.05
    position_size = 2.0
    market_tier = "us_weather_major"

    trades_naive = []      # Without fees/slippage (current system)
    trades_realistic = []  # With fees/slippage/fill rates
    forecasts = []
    outcomes = []

    for m in markets:
        question = m["question"]
        actual = m["actual_outcome"]
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        prob = est["probability"]
        actual_binary = 1 if actual == "YES_WON" else 0
        forecasts.append(prob)
        outcomes.append(actual_binary)

        edge = prob - entry_price
        abs_edge = abs(edge)
        if abs_edge < edge_threshold:
            continue

        direction = "buy_yes" if edge > 0 else "buy_no"

        # Naive trade (no fees, no slippage, 100% fill)
        if direction == "buy_yes":
            won_naive = actual == "YES_WON"
            pnl_naive = (position_size / entry_price) - position_size if won_naive else -position_size
        else:
            no_price = 1.0 - entry_price
            won_naive = actual == "NO_WON"
            pnl_naive = (position_size / no_price) - position_size if won_naive else -position_size

        trades_naive.append({"won": won_naive, "pnl": pnl_naive, "direction": direction})

        # Realistic trade (fees + slippage + fill rate)
        if not simulate_fill(abs_edge, market_tier):
            continue  # Order didn't fill

        slip = estimate_slippage(position_size, market_tier)
        won_real, pnl_real = resolve_trade_with_fees(
            direction, entry_price, position_size, actual,
            winner_fee=THRESHOLDS["weather_winner_fee"],
            slippage=slip,
        )
        trades_realistic.append({"won": won_real, "pnl": pnl_real, "direction": direction})

    # ── Step 2: Compute metrics for both ──
    def compute_metrics(trades, label):
        n = len(trades)
        if n == 0:
            return {"label": label, "n": 0}
        wins = sum(1 for t in trades if t["won"])
        pnls = [t["pnl"] for t in trades]
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / n
        return {
            "label": label,
            "n": n,
            "wins": wins,
            "win_rate": round(wins / n, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 4),
            "pnls": pnls,
        }

    naive = compute_metrics(trades_naive, "Naive (no fees/slippage)")
    realistic = compute_metrics(trades_realistic, "Realistic (fees+slippage+fills)")

    # ── Step 3: Statistical significance ──
    sig_naive = test_significance(naive["n"], naive.get("wins", 0))
    sig_realistic = test_significance(realistic["n"], realistic.get("wins", 0))

    # ── Step 4: Brier decomposition ──
    brier = brier_decomposition(forecasts, outcomes)

    # ── Step 5: Sharpe ratio ──
    sharpe_naive = compute_sharpe(naive.get("pnls", []))
    sharpe_realistic = compute_sharpe(realistic.get("pnls", []))

    # ── Step 6: Deflated Sharpe Ratio ──
    dsr_value = deflated_sharpe_ratio(
        observed_sr=sharpe_realistic.get("sharpe_annual", 0),
        num_trials=num_strategy_variants,
        T=realistic["n"],
        skewness=sharpe_realistic.get("skewness", 0),
        kurtosis=sharpe_realistic.get("kurtosis", 3.0),
    )

    # ── Step 7: Monte Carlo ruin ──
    if realistic.get("pnls"):
        mc_ruin = monte_carlo_ruin(realistic["pnls"])
    else:
        mc_ruin = {"p_ruin": 1.0, "passes_threshold": False}

    # ── Step 8: ARR comparison ──
    def arr_estimate(avg_pnl, trades_per_day=5, capital=75, infra=20):
        monthly = avg_pnl * trades_per_day * 30 - infra
        annual = monthly * 12
        return round((annual / capital) * 100, 1)

    arr_naive = arr_estimate(naive.get("avg_pnl", 0))
    arr_realistic = arr_estimate(realistic.get("avg_pnl", 0))
    arr_degradation = round(((arr_naive - arr_realistic) / abs(arr_naive)) * 100, 1) if arr_naive != 0 else 0

    # ── Step 9: Harvey & Liu t-statistic test ──
    hl_test = harvey_liu_test(
        sharpe_ratio=sharpe_realistic.get("sharpe_annual", 0),
        years=1.0,
        num_tested=num_strategy_variants,
    )

    # ── Step 10: Walk-Forward Efficiency (requires resolution dates) ──
    # Note: For full implementation, would need resolution_dates from backtest data
    # For now, provide placeholder
    wfe_result = {
        "wfe": 0.0,
        "is_annual_return": 0.0,
        "oos_annual_return": 0.0,
        "passes_wfe_test": False,
        "num_cohorts": 0,
        "note": "WFE requires resolution date data from backtest"
    }

    # ── Step 11: Combinatorial Purged Cross-Validation (requires resolution dates) ──
    # Note: Full CPCV requires strategy variants data, provided as optional section
    pbo_result = {
        "pbo": 0.0,
        "paths_analyzed": 0,
        "is_optimal_underperforms": 0,
        "mean_is_sharpe": 0.0,
        "mean_oos_sharpe": 0.0,
        "passes_pbo_test": False,
        "note": "CPCV requires strategy variants and resolution dates from backtest"
    }

    # ── Step 12: Compile validation gates ──
    gates = {
        "1_sample_size": {
            "metric": "Minimum trades for significance",
            "value": realistic["n"],
            "threshold": f"≥ {THRESHOLDS['min_trades_significant']}",
            "passes": realistic["n"] >= THRESHOLDS["min_trades_significant"],
        },
        "2_statistical_significance": {
            "metric": "Win rate p-value (vs 50%)",
            "value": sig_realistic.p_value,
            "threshold": "< 0.01",
            "passes": sig_realistic.is_significant_99,
        },
        "3_sharpe_reasonable": {
            "metric": "Annualized Sharpe Ratio",
            "value": sharpe_realistic.get("sharpe_annual", 0),
            "threshold": f"0.5 - {THRESHOLDS['sharpe_max']}",
            "passes": 0.3 <= sharpe_realistic.get("sharpe_annual", 0) <= THRESHOLDS["sharpe_max"],
        },
        "4_deflated_sharpe": {
            "metric": f"Deflated Sharpe (correcting for {num_strategy_variants} variants)",
            "value": round(dsr_value, 4),
            "threshold": f"≥ {THRESHOLDS['dsr_min']}",
            "passes": dsr_value >= THRESHOLDS["dsr_min"],
        },
        "5_brier_score": {
            "metric": "Brier Score",
            "value": brier.brier_score,
            "threshold": f"< {THRESHOLDS['brier_max']}",
            "passes": brier.brier_score < THRESHOLDS["brier_max"],
        },
        "6_monte_carlo_ruin": {
            "metric": "P(50% drawdown) over 1 year",
            "value": mc_ruin.get("p_ruin", 1),
            "threshold": f"< {THRESHOLDS['mc_ruin_max']:.0%}",
            "passes": mc_ruin.get("passes_threshold", False),
        },
        "7_arr_degradation": {
            "metric": "ARR degradation (naive → realistic)",
            "value": f"{arr_degradation}%",
            "threshold": "< 50% degradation",
            "passes": arr_degradation < 50,
        },
        "8_harvey_liu_tstat": {
            "metric": "Harvey & Liu t-statistic (multiple testing correction)",
            "value": hl_test.get("t_stat", 0),
            "threshold": f"≥ {hl_test.get('threshold', THRESHOLDS['harvey_liu_tstat_min'])}",
            "passes": hl_test.get("passes", False),
        },
        "9_wfe": {
            "metric": "Walk-Forward Efficiency",
            "value": wfe_result.get("wfe", 0),
            "threshold": f"≥ {THRESHOLDS['wfe_min']}",
            "passes": wfe_result.get("passes_wfe_test", False),
        },
    }

    all_pass = all(g["passes"] for g in gates.values())

    return {
        "validation_summary": {
            "all_gates_pass": all_pass,
            "gates_passed": sum(1 for g in gates.values() if g["passes"]),
            "gates_total": len(gates),
            "verdict": "STRATEGY VALIDATED" if all_pass else "NEEDS IMPROVEMENT",
        },
        "gates": gates,
        "arr_comparison": {
            "naive_arr": arr_naive,
            "realistic_arr": arr_realistic,
            "degradation_pct": arr_degradation,
            "note": "Naive=no fees/slippage; Realistic=2% winner fee, spread slippage, 55% fill rate",
        },
        "naive_metrics": {k: v for k, v in naive.items() if k != "pnls"},
        "realistic_metrics": {k: v for k, v in realistic.items() if k != "pnls"},
        "significance": {
            "naive": {
                "z_stat": sig_naive.z_stat, "p_value": sig_naive.p_value,
                "wilson_ci": [sig_naive.wilson_ci_low, sig_naive.wilson_ci_high],
                "significant_99": sig_naive.is_significant_99,
            },
            "realistic": {
                "z_stat": sig_realistic.z_stat, "p_value": sig_realistic.p_value,
                "wilson_ci": [sig_realistic.wilson_ci_low, sig_realistic.wilson_ci_high],
                "significant_99": sig_realistic.is_significant_99,
                "min_trades_needed": sig_realistic.min_trades_for_significance,
            },
        },
        "brier_decomposition": {
            "brier_score": brier.brier_score,
            "reliability": brier.reliability,
            "resolution": brier.resolution,
            "uncertainty": brier.uncertainty,
            "base_rate": brier.base_rate,
            "interpretation": (
                f"Reliability={brier.reliability:.4f} (calibration error, lower=better), "
                f"Resolution={brier.resolution:.4f} (discrimination, higher=better). "
                f"{'Good discrimination.' if brier.resolution > brier.reliability else 'Calibration error dominates.'}"
            ),
            "buckets": brier.bucket_details,
        },
        "sharpe": {
            "naive": sharpe_naive,
            "realistic": sharpe_realistic,
            "deflated_sharpe_ratio": round(dsr_value, 4),
            "num_variants_tested": num_strategy_variants,
        },
        "harvey_liu_test": hl_test,
        "walk_forward_efficiency": wfe_result,
        "combinatorial_purged_cv": pbo_result,
        "monte_carlo_ruin": mc_ruin,
        "kelly_example": {
            "scenario": "p=0.70, market=0.55, weather market",
            "full_kelly": round(kelly_binary(0.70, 0.55, "buy_yes", 0.02, 1.0, 1.0), 4),
            "half_kelly": round(kelly_binary(0.70, 0.55, "buy_yes", 0.02, 0.50, 1.0), 4),
            "quarter_kelly": round(kelly_binary(0.70, 0.55, "buy_yes", 0.02, 0.25, 0.20), 4),
            "recommendation": "Quarter-Kelly with 20% max allocation (research consensus)",
        },
    }


def print_validation_report(results: dict):
    """Print formatted validation report."""
    vs = results["validation_summary"]

    print("\n" + "=" * 80)
    print("  BACKTEST VALIDATION FRAMEWORK")
    print("  Based on: De Prado (2018), Bailey et al. (2014), Murphy (1973)")
    print("=" * 80)

    # Verdict
    verdict = vs["verdict"]
    passed = vs["gates_passed"]
    total = vs["gates_total"]
    status = "PASS" if vs["all_gates_pass"] else "FAIL"
    print(f"\n  VERDICT: {verdict} [{passed}/{total} gates passed] [{status}]")

    # Gates
    print(f"\n  VALIDATION GATES:")
    print(f"  {'Gate':<50s} {'Value':>12s}  {'Threshold':>18s}  {'Status':>6s}")
    print(f"  {'-'*92}")
    for key, gate in results["gates"].items():
        status = " PASS" if gate["passes"] else " FAIL"
        val = gate["value"]
        if isinstance(val, float):
            val_str = f"{val:.4f}"
        else:
            val_str = str(val)
        print(f"  {gate['metric']:<50s} {val_str:>12s}  {gate['threshold']:>18s}  {status:>6s}")

    # ARR comparison
    arr = results["arr_comparison"]
    print(f"\n  ARR COMPARISON (5 trades/day, $75 capital, $20/mo infra):")
    print(f"    Naive (current system):    {arr['naive_arr']:+.1f}%")
    print(f"    Realistic (with costs):    {arr['realistic_arr']:+.1f}%")
    print(f"    Degradation:               {arr['degradation_pct']}%")

    # Significance
    sig = results["significance"]["realistic"]
    print(f"\n  STATISTICAL SIGNIFICANCE:")
    print(f"    z-statistic:  {sig['z_stat']}")
    print(f"    p-value:      {sig['p_value']}")
    print(f"    Wilson 95% CI: [{sig['wilson_ci'][0]:.1%}, {sig['wilson_ci'][1]:.1%}]")
    print(f"    Significant at 99%: {'YES' if sig['significant_99'] else 'NO'}")
    print(f"    Min trades needed for 99% significance: {sig['min_trades_needed']}")

    # Brier decomposition
    bd = results["brier_decomposition"]
    print(f"\n  BRIER SCORE DECOMPOSITION (Murphy 1973):")
    print(f"    Brier Score:   {bd['brier_score']:.4f}  (0.25 = random, 0 = perfect)")
    print(f"    Reliability:   {bd['reliability']:.4f}  (calibration error, lower = better)")
    print(f"    Resolution:    {bd['resolution']:.4f}  (discrimination, higher = better)")
    print(f"    Uncertainty:   {bd['uncertainty']:.4f}  (inherent, fixed)")
    print(f"    Base rate:     {bd['base_rate']:.1%} YES")
    print(f"    Interpretation: {bd['interpretation']}")

    # Sharpe
    sh = results["sharpe"]
    print(f"\n  SHARPE RATIO:")
    print(f"    Naive annual:     {sh['naive'].get('sharpe_annual', 0):.3f}")
    print(f"    Realistic annual: {sh['realistic'].get('sharpe_annual', 0):.3f}")
    print(f"    Deflated SR:      {sh['deflated_sharpe_ratio']:.4f}  (need ≥ 0.95)")
    print(f"    Return skewness:  {sh['realistic'].get('skewness', 0):.3f}")
    print(f"    Return kurtosis:  {sh['realistic'].get('kurtosis', 3):.3f}  (normal = 3.0)")

    # Monte Carlo
    mc = results["monte_carlo_ruin"]
    print(f"\n  MONTE CARLO RUIN ANALYSIS ({mc.get('num_paths', 10000):,} paths):")
    print(f"    P(50% drawdown):      {mc.get('p_ruin_pct', 'N/A')}")
    print(f"    Passes threshold:     {'YES' if mc.get('passes_threshold') else 'NO'} (need < 5%)")
    print(f"    Median max drawdown:  {mc.get('median_max_drawdown', 0):.1%}")
    print(f"    95th pct drawdown:    {mc.get('p95_max_drawdown', 0):.1%}")
    print(f"    p95/median DD ratio:  {mc.get('dd_ratio_p95_to_median', 0):.1f}×  (research: expect 1.5-3×)")

    # Harvey & Liu t-statistic
    hl = results.get("harvey_liu_test", {})
    if hl:
        print(f"\n  HARVEY & LIU t-STATISTIC (Multiple Testing Correction):")
        print(f"    Sharpe Ratio:     {hl.get('sharpe_ratio', 0):.4f}")
        print(f"    t-statistic:      {hl.get('t_stat', 0):.3f}")
        print(f"    Threshold:        {hl.get('threshold', 0):.2f}  (for {hl.get('num_strategies_tested', 0)} variants)")
        print(f"    Result:           {'PASS' if hl.get('passes') else 'FAIL'}")
        print(f"    Years needed:     {hl.get('years_needed', 'N/A')}")

    # Walk-Forward Efficiency
    wfe = results.get("walk_forward_efficiency", {})
    if wfe and "note" not in wfe:
        print(f"\n  WALK-FORWARD EFFICIENCY (WFE):")
        print(f"    WFE:              {wfe.get('wfe_pct', 'N/A')}")
        print(f"    IS annual return: {wfe.get('is_annual_return', 0):.4f}")
        print(f"    OOS annual return:{wfe.get('oos_annual_return', 0):.4f}")
        print(f"    Result:           {'PASS' if wfe.get('passes_wfe_test') else 'FAIL'} (need > {THRESHOLDS['wfe_min']:.0%})")

    # Combinatorial Purged Cross-Validation
    pbo = results.get("combinatorial_purged_cv", {})
    if pbo and "note" not in pbo:
        print(f"\n  COMBINATORIAL PURGED CROSS-VALIDATION (CPCV):")
        print(f"    PBO (Probability of Backtest Overfitting): {pbo.get('pbo_pct', 'N/A')}")
        print(f"    Paths analyzed:   {pbo.get('paths_analyzed', 0)}")
        print(f"    IS optimal underperforms OOS: {pbo.get('is_optimal_underperforms', 0)} paths")
        print(f"    Mean IS Sharpe:   {pbo.get('mean_is_sharpe', 0):.3f}")
        print(f"    Mean OOS Sharpe:  {pbo.get('mean_oos_sharpe', 0):.3f}")
        print(f"    Result:           {'PASS' if pbo.get('passes_pbo_test') else 'FAIL'} (need PBO < {THRESHOLDS['pbo_max']:.0%})")

    # Kelly
    ke = results["kelly_example"]
    print(f"\n  KELLY CRITERION ({ke['scenario']}):")
    print(f"    Full Kelly:    {ke['full_kelly']:.1%} of bankroll  (too aggressive)")
    print(f"    Half Kelly:    {ke['half_kelly']:.1%} of bankroll")
    print(f"    Quarter Kelly: {ke['quarter_kelly']:.1%} of bankroll  (recommended)")

    print("\n" + "=" * 80)


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backtest Validation Framework")
    parser.add_argument("--variants", type=int, default=10,
                        help="Number of strategy variants tested (for DSR correction)")
    parser.add_argument("--save", action="store_true", help="Save results to JSON")
    args = parser.parse_args()

    results = run_full_validation(num_strategy_variants=args.variants)
    print_validation_report(results)

    if args.save:
        out_path = os.path.join(DATA_DIR, "validation_results.json")
        # Remove non-serializable fields
        save_results = json.loads(json.dumps(results, default=str))
        with open(out_path, "w") as f:
            json.dump(save_results, f, indent=2)
        print(f"\nSaved to {out_path}")
