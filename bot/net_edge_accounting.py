"""
Net Edge Accounting — Core EV Formulas for All Edge Families
=============================================================
Dispatch: DISPATCH_107 (Deep Research Integration)

Every signal in the system must pass through these formulas before
capital is allocated. No exceptions.

Source: ChatGPT Deep Research report (March 2026), validated against:
- Almgren & Chriss (2000) optimal execution
- Aquilina, Budish & O'Neill (2022) latency arbitrage
- Harvey, Liu & Zhu (2016) multiple testing in finance

Usage:
    from bot.net_edge_accounting import net_edge, maker_ev, capital_velocity
    from bot.net_edge_accounting import deflated_sharpe, kelly_binary
    from bot.net_edge_accounting import bayesian_bin_calibration

Author: JJ (autonomous)
Date: 2026-03-23
"""

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("JJ.net_edge_accounting")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class Venue(Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    ALPACA = "alpaca"


@dataclass
class FeeSchedule:
    """Venue-specific fee schedule."""
    maker_fee: float = 0.0       # fraction (0.0 = free)
    taker_fee: float = 0.02      # fraction
    maker_rebate: float = 0.0    # fraction (0.20 = 20% rebate from pool)
    min_order_usd: float = 1.0
    venue: Venue = Venue.POLYMARKET

    @staticmethod
    def polymarket() -> "FeeSchedule":
        return FeeSchedule(
            maker_fee=0.0, taker_fee=0.02,
            maker_rebate=0.20, min_order_usd=1.0,
            venue=Venue.POLYMARKET,
        )

    @staticmethod
    def kalshi() -> "FeeSchedule":
        return FeeSchedule(
            maker_fee=0.0, taker_fee=0.07,
            maker_rebate=0.0, min_order_usd=1.0,
            venue=Venue.KALSHI,
        )

    @staticmethod
    def alpaca() -> "FeeSchedule":
        return FeeSchedule(
            maker_fee=0.0, taker_fee=0.0,
            maker_rebate=0.0, min_order_usd=1.0,
            venue=Venue.ALPACA,
        )


@dataclass
class CostBreakdown:
    """Itemized cost breakdown for a single trade."""
    fees: float = 0.0
    slippage: float = 0.0
    latency_penalty: float = 0.0
    non_fill_penalty: float = 0.0
    impact_cost: float = 0.0

    @property
    def total(self) -> float:
        return (self.fees + self.slippage + self.latency_penalty
                + self.non_fill_penalty + self.impact_cost)


@dataclass
class EdgeResult:
    """Result of edge computation for a single signal."""
    gross_edge_bps: float
    net_edge_bps: float
    costs: CostBreakdown
    maker_ev_usd: float
    kelly_fraction: float
    capital_velocity: float  # annualized edge per hour of capital locked
    is_tradeable: bool
    kill_reason: str = ""

    @property
    def net_edge_pct(self) -> float:
        return self.net_edge_bps / 10_000


# ---------------------------------------------------------------------------
# Core formulas (from Deep Research report)
# ---------------------------------------------------------------------------

def net_edge(gross_edge: float, fees: float, slippage: float,
             latency_penalty: float = 0.0,
             non_fill_penalty: float = 0.0) -> float:
    """
    Net edge after all costs. All inputs in same units (USD or fraction).

    Formula:
        net_edge = gross_edge - fees - slippage - latency_penalty - non_fill_penalty
    """
    return gross_edge - fees - slippage - latency_penalty - non_fill_penalty


def maker_ev(p_fill: float, p_win_given_fill: float,
             payoff: float, loss: float,
             cancel_cost: float = 0.0) -> float:
    """
    Expected value of a maker order, accounting for fill uncertainty.

    Formula:
        EV_maker = P(fill) * [P(win|fill) * payoff - P(loss|fill) * loss] - cancel_cost

    Args:
        p_fill: probability order gets filled (0 to 1)
        p_win_given_fill: probability of winning conditional on fill
        payoff: profit if filled and correct (USD)
        loss: loss if filled and wrong (USD)
        cancel_cost: cost of placing + cancelling unfilled orders
    """
    return p_fill * (p_win_given_fill * payoff - (1 - p_win_given_fill) * loss) - cancel_cost


def capital_velocity(expected_pnl: float, capital_locked: float,
                     hours_locked: float) -> float:
    """
    Capital velocity: how fast locked capital generates returns.

    Formula:
        capital_velocity = E[net PnL] / (capital_locked * hours_locked)

    Higher is better. Critical for small bankroll compounding.
    Returns annualized rate.
    """
    if capital_locked <= 0 or hours_locked <= 0:
        return 0.0
    hourly_return = expected_pnl / (capital_locked * hours_locked)
    return hourly_return * 8760  # annualize (365 * 24)


def kelly_binary(p_win: float, odds: float) -> float:
    """
    Kelly fraction for a binary bet.

    Formula:
        f* = (p * b - q) / b

    where p = P(win), q = 1-p, b = net odds (payoff/loss ratio).

    Returns 0 if edge is non-positive. Caps at 0.25 (quarter-Kelly).
    """
    if p_win <= 0 or p_win >= 1 or odds <= 0:
        return 0.0
    q = 1 - p_win
    f = (p_win * odds - q) / odds
    if f <= 0:
        return 0.0
    return min(f, 0.25)  # quarter-Kelly hard cap


def kelly_prediction_market(p_actual: float, p_market: float) -> float:
    """
    Kelly fraction specifically for prediction market contracts.

    For a NO position at price (1 - p_market):
        Buy NO at cost = (1 - p_market)
        Win (event doesn't happen): profit = p_market
        Lose (event happens): lose (1 - p_market)

    Returns quarter-Kelly fraction.
    """
    if p_market <= 0 or p_market >= 1 or p_actual <= 0 or p_actual >= 1:
        return 0.0

    # Buying NO: cost = (1 - p_market), payoff if correct = p_market
    p_no_wins = 1 - p_actual  # true probability event doesn't happen
    cost = 1 - p_market
    payoff = p_market
    odds = payoff / cost if cost > 0 else 0.0

    return kelly_binary(p_no_wins, odds)


# ---------------------------------------------------------------------------
# Impact cost model (square-root)
# ---------------------------------------------------------------------------

def impact_cost(order_size: float, adv: float, sigma: float,
                k: float = 0.1) -> float:
    """
    Square-root impact model (Almgren-Chriss style).

    Formula:
        impact = k * sigma * sqrt(Q / ADV)

    Args:
        order_size: order size in USD
        adv: average daily volume in USD
        sigma: daily volatility (fraction)
        k: impact coefficient (calibrate empirically; 0.1 default)
    """
    if adv <= 0 or sigma <= 0:
        return 0.0
    return k * sigma * math.sqrt(order_size / adv)


# ---------------------------------------------------------------------------
# Polymarket fee model
# ---------------------------------------------------------------------------

def polymarket_fee(price: float, fee_rate: float = 0.02,
                   is_maker: bool = True) -> float:
    """
    Polymarket fee formula: fee = price * (1 - price) * rate
    Peaks at 50/50 odds (price = 0.50).
    Maker fee is 0.0. This computes taker fee.
    """
    if is_maker:
        return 0.0
    return price * (1.0 - price) * fee_rate


# ---------------------------------------------------------------------------
# Bayesian tail calibration (for FLB harvesting)
# ---------------------------------------------------------------------------

@dataclass
class BinCalibration:
    """Calibration result for a single probability bin."""
    bin_center: float
    observed_rate: float
    sample_size: int
    posterior_mean: float
    credible_lower: float  # 5th percentile
    credible_upper: float  # 95th percentile
    bin_error: float       # observed - expected
    edge_bps: float        # (observed/expected - 1) * 10000


def bayesian_bin_calibration(wins: int, total: int,
                             bin_center: float,
                             prior_alpha: float = 1.0,
                             prior_beta: float = 1.0) -> BinCalibration:
    """
    Bayesian-binomial shrinkage for a probability bin.

    Formula:
        p | wins, losses ~ Beta(alpha + wins, beta + losses)
        posterior_mean = (alpha + wins) / (alpha + beta + total)

    Uses Beta distribution for credible intervals.
    Conservative lower bound is used for sizing decisions.
    """
    losses = total - wins
    alpha = prior_alpha + wins
    beta = prior_beta + losses

    posterior_mean = alpha / (alpha + beta)

    # Credible intervals via Beta quantile approximation
    # Using normal approximation for Beta when alpha, beta > 5
    if alpha > 2 and beta > 2:
        var = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
        std = math.sqrt(var)
        credible_lower = max(0.0, posterior_mean - 1.645 * std)
        credible_upper = min(1.0, posterior_mean + 1.645 * std)
    else:
        # Very sparse: use wide bounds
        credible_lower = max(0.0, posterior_mean - 0.20)
        credible_upper = min(1.0, posterior_mean + 0.20)

    observed_rate = wins / total if total > 0 else 0.0
    bin_error = observed_rate - bin_center

    # Edge in basis points: how much the market overprices YES
    # For FLB: if bin_center is 0.05 (market says 5%) but observed is 3%,
    # then NO side is underpriced → edge for NO buyer
    if bin_center > 0:
        edge_ratio = (observed_rate / bin_center) - 1.0
    else:
        edge_ratio = 0.0
    edge_bps = edge_ratio * 10_000

    return BinCalibration(
        bin_center=bin_center,
        observed_rate=observed_rate,
        sample_size=total,
        posterior_mean=posterior_mean,
        credible_lower=credible_lower,
        credible_upper=credible_upper,
        bin_error=bin_error,
        edge_bps=edge_bps,
    )


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio (multiple testing correction)
# ---------------------------------------------------------------------------

def deflated_sharpe(observed_sharpe: float, num_trials: int,
                    T: int, skew: float = 0.0,
                    kurtosis: float = 3.0) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Adjusts observed Sharpe for the number of strategy trials tested.
    Returns the probability that the observed Sharpe exceeds what you'd
    expect from the best of `num_trials` random strategies.

    Formula:
        E[max(SR)] ~ sqrt(2 * ln(N)) * (1 - gamma/sqrt(2*ln(N))) + gamma/sqrt(2*ln(N))
        where gamma ~ 0.5772 (Euler-Mascheroni)

    Args:
        observed_sharpe: the Sharpe ratio you measured
        num_trials: number of strategies tested (total, including failures)
        T: number of observations (trade count)
        skew: return distribution skewness
        kurtosis: return distribution kurtosis (3.0 = normal)
    """
    if num_trials <= 0 or T <= 0:
        return 0.0

    gamma = 0.5772  # Euler-Mascheroni constant

    # Expected max Sharpe from num_trials random strategies
    ln_n = math.log(max(num_trials, 2))
    sqrt_2ln = math.sqrt(2 * ln_n)
    expected_max_sr = sqrt_2ln * (1 - gamma / sqrt_2ln) + gamma / sqrt_2ln

    # Standard error of Sharpe estimator (corrected for non-normality)
    se_sr = math.sqrt(
        (1 + 0.25 * (skew ** 2) * observed_sharpe ** 2
         + ((kurtosis - 3) / 4) * observed_sharpe ** 2) / T
    )

    if se_sr <= 0:
        return 0.0

    # Test statistic: how many SE above expected max
    z = (observed_sharpe - expected_max_sr) / se_sr

    # Convert to probability using normal CDF approximation
    return _normal_cdf(z)


def _normal_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Full edge evaluation (combines all formulas)
# ---------------------------------------------------------------------------

def evaluate_edge(
    gross_edge_bps: float,
    p_fill: float,
    p_win: float,
    position_usd: float,
    hours_locked: float,
    fee_schedule: FeeSchedule,
    spread_bps: float = 0.0,
    adv: float = 10000.0,
    sigma: float = 0.5,
    is_maker: bool = True,
    min_net_edge_bps: float = 10.0,
) -> EdgeResult:
    """
    Full edge evaluation pipeline. Returns tradeable/kill decision.

    This is the central gateway: every signal in the system must pass through
    this function before capital is allocated.
    """
    # Cost computation
    price_mid = 0.50  # approximate for fee calc
    fees = fee_schedule.maker_fee if is_maker else polymarket_fee(price_mid, fee_schedule.taker_fee, is_maker=False)
    fees_usd = fees * position_usd

    slippage_bps = spread_bps / 2 if is_maker else spread_bps
    slippage_usd = (slippage_bps / 10_000) * position_usd

    impact = impact_cost(position_usd, adv, sigma) * position_usd
    latency_pen = 0.0  # computed by latency_surface module
    non_fill_pen = (1 - p_fill) * (gross_edge_bps / 10_000) * position_usd if not is_maker else 0.0

    costs = CostBreakdown(
        fees=fees_usd,
        slippage=slippage_usd,
        latency_penalty=latency_pen,
        non_fill_penalty=non_fill_pen,
        impact_cost=impact,
    )

    gross_usd = (gross_edge_bps / 10_000) * position_usd
    net_usd = net_edge(gross_usd, costs.fees, costs.slippage,
                       costs.latency_penalty, costs.non_fill_penalty)
    net_bps = (net_usd / position_usd) * 10_000 if position_usd > 0 else 0.0

    # Maker EV
    payoff_usd = (gross_edge_bps / 10_000) * position_usd
    loss_usd = position_usd * 0.5  # approximate max loss
    mev = maker_ev(p_fill, p_win, payoff_usd, loss_usd)

    # Kelly
    if gross_edge_bps > 0 and p_win > 0.5:
        odds = p_win / (1 - p_win)
        kf = kelly_binary(p_win, odds)
    else:
        kf = 0.0

    # Capital velocity
    cv = capital_velocity(net_usd, position_usd, hours_locked)

    # Kill decision
    is_tradeable = net_bps >= min_net_edge_bps
    kill_reason = ""
    if not is_tradeable:
        if net_bps <= 0:
            kill_reason = "negative_net_edge"
        else:
            kill_reason = f"net_edge_{net_bps:.1f}bps_below_threshold_{min_net_edge_bps:.0f}bps"

    result = EdgeResult(
        gross_edge_bps=gross_edge_bps,
        net_edge_bps=net_bps,
        costs=costs,
        maker_ev_usd=mev,
        kelly_fraction=kf,
        capital_velocity=cv,
        is_tradeable=is_tradeable,
        kill_reason=kill_reason,
    )

    if is_tradeable:
        logger.info("TRADEABLE: net_edge=%.1fbps kelly=%.4f cv=%.2f",
                     net_bps, kf, cv)
    else:
        logger.debug("KILL: %s (gross=%.1fbps net=%.1fbps)",
                      kill_reason, gross_edge_bps, net_bps)

    return result
