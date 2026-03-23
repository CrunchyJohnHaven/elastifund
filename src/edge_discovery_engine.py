#!/usr/bin/env python3
"""
Edge Discovery Engine — Continuous Hypothesis Generation and Kill Testing
=========================================================================
DISPATCH_108: Complementary daemon to the Evolution Loop.

The Evolution Loop optimizes EXISTING strategy genomes via crossover and
mutation. This engine does something different: it systematically enumerates
the space of untested hypotheses, simulates each via walk-forward backtesting,
applies rigorous Bayesian kill rules, and surfaces only the survivors.

Three hypothesis generation methods:
  1. Parameter sweep over existing strategies in src/strategies/
  2. Combinatorial feature selection from signal sources
  3. Research-driven seeding from research/edge_backlog_ranked.md

Kill criteria (strict, multi-layer):
  - Net edge kill: P(mu_ell > 0) < 0.30 after 30+ simulated trades
  - Fee kill: fee drag > 50% of gross edge
  - Density kill: < 1 opportunity per day
  - Fill kill: P(fill) < 10% for maker strategies
  - Drawdown kill: max DD > 3x avg daily PnL
  - Multiple testing: Benjamini-Hochberg FDR at alpha=0.10

Promotion criteria (all must pass):
  - P(mu > 0) >= 0.90
  - Net edge positive after 2x fee stress
  - Density >= 2 opportunities per day
  - Fill rate >= 20% (maker)
  - Survives 3+ walk-forward windows
  - Passes Benjamini-Hochberg FDR correction

Usage:
  python3 src/edge_discovery_engine.py --max-hypotheses 10
  python3 src/edge_discovery_engine.py --max-hypotheses 50 --cycle-timeout 3600

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup: ensure repo root is on sys.path
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("JJ.edge_discovery")

# ---------------------------------------------------------------------------
# Hypothesis dataclass
# ---------------------------------------------------------------------------


@dataclass
class EdgeHypothesis:
    """
    A single tradeable edge hypothesis — the atomic unit of the discovery engine.

    Each hypothesis encodes a complete strategy specification:
    - WHAT to trade (venue, category)
    - WHEN to trade (entry logic with conditions)
    - HOW to size it (fee model, Kelly constraints)
    - HOW to kill it (explicit kill conditions before wasting live capital)
    """
    hypothesis_id: str
    strategy_family: str          # "longshot_fade", "latency_capture", "maker_micro",
                                  # "structural_basket", "time_decay", "cross_platform_arb",
                                  # "sentiment_fade", "data_release", "combinatorial"
    venue: str                    # "polymarket", "kalshi", "alpaca"
    parameters: dict              # Family-specific parameters
    entry_logic: str              # Human-readable entry conditions
    exit_logic: str               # Human-readable exit conditions
    fee_model: str                # "maker_rebate", "taker_flat", "maker_flat", "zero_fee"
    expected_sign: str            # "positive" or "negative" (direction of alpha)
    kill_conditions: list[str]    # Pre-specified kill rules for this hypothesis
    created_at: datetime
    status: str                   # "pending", "testing", "killed", "survivor"

    # Populated after walk-forward evaluation
    posterior: Optional[dict] = None          # LogGrowthPosterior serialized
    walk_forward_windows: int = 0
    opportunity_density_per_day: float = 0.0
    fill_rate_estimate: float = 0.0
    max_drawdown: float = 0.0
    net_pnl_after_fees: float = 0.0
    kill_reason: Optional[str] = None
    promoted_at: Optional[datetime] = None

    @property
    def fingerprint(self) -> str:
        """Deterministic ID for deduplication."""
        blob = json.dumps({
            "family": self.strategy_family,
            "venue": self.venue,
            "params": self.parameters,
        }, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        d["promoted_at"] = self.promoted_at.isoformat() if self.promoted_at else None
        return d


# ---------------------------------------------------------------------------
# Walk-forward evaluation result
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardResult:
    """Metrics from a single walk-forward window."""
    window_index: int
    train_start: int    # Unix timestamp
    train_end: int
    test_start: int
    test_end: int
    n_trades: int
    gross_pnl: float
    fee_drag: float
    net_pnl: float
    win_rate: float
    max_drawdown: float
    sharpe: float
    opportunity_density: float   # trades / day in test window
    fill_rate: float


@dataclass
class EvaluationResult:
    """Aggregated result across all walk-forward windows."""
    hypothesis_id: str
    windows: list[WalkForwardResult]
    posterior_dict: dict          # LogGrowthPosterior serialized
    prob_positive: float
    net_edge_positive: bool
    fee_stress_survives: bool     # net positive at 2x fees
    density_ok: bool              # >= 2 opp/day
    fill_rate_ok: bool            # >= 20% for maker
    drawdown_ok: bool             # max DD < 3x avg daily PnL
    bh_fdr_passes: bool
    kill_reason: Optional[str]
    is_survivor: bool
    total_simulated_trades: int
    avg_net_pnl_per_window: float
    opportunity_density_per_day: float
    max_drawdown: float


# ---------------------------------------------------------------------------
# Synthetic data generator (for use when no historical data exists)
# ---------------------------------------------------------------------------


def _generate_synthetic_market_data(
    n_markets: int = 500,
    seed: int = 42,
    family: str = "maker_micro",
    parameters: Optional[dict] = None,
) -> list[dict]:
    """
    Generate synthetic market records for hypothesis testing.

    When historical data is unavailable, generate plausible synthetic records
    using domain knowledge about Polymarket market structure. The statistical
    properties are calibrated from the observed 532-market walk-forward dataset.

    Synthetic properties (calibrated from observed data):
    - Entry prices: Beta(5, 5) distribution (cluster around 0.45-0.55)
    - Win rate: ~52% base for well-calibrated predictions
    - VPIN: half-normal centered at 0.15-0.35
    - Spread: log-normal with mu=0.03, sigma=0.5
    - Hour-of-day: uniform with slight 03-06 ET weighting (from BTC5 findings)
    """
    rng = random.Random(seed)
    params = parameters or {}

    markets = []
    for i in range(n_markets):
        # Entry price: varies by strategy family
        if family == "longshot_fade":
            # Longshots: entry near 0.85-0.95 for YES (we short via NO)
            entry_price = 0.85 + rng.betavariate(2, 1) * 0.10
            side = "NO"
        elif family == "maker_micro":
            entry_price = 0.40 + rng.betavariate(5, 5) * 0.20
            side = rng.choice(["YES", "NO"])
        elif family == "time_decay":
            entry_price = 0.75 + rng.betavariate(3, 1) * 0.20
            side = "YES"
        else:
            entry_price = 0.30 + rng.betavariate(5, 5) * 0.40
            side = rng.choice(["YES", "NO"])

        # VPIN: toxic flow indicator
        vpin = max(0.0, min(1.0, rng.gauss(0.25, 0.15)))

        # Spread
        raw_spread = math.exp(rng.gauss(math.log(0.04), 0.4))
        spread = max(0.01, min(0.20, raw_spread))

        # Hour of day (ET)
        hour_weights = [
            0.4, 0.3, 0.3, 0.6, 0.7, 0.8, 0.6, 0.5,  # 00-07
            0.4, 0.5, 0.7, 0.8, 0.9, 1.0, 1.0, 0.9,  # 08-15
            0.8, 0.7, 0.6, 0.5, 0.5, 0.4, 0.4, 0.4,  # 16-23
        ]
        hour = rng.choices(range(24), weights=hour_weights)[0]

        # Book imbalance
        book_imbalance = rng.gauss(0.0, 0.20)
        book_imbalance = max(-1.0, min(1.0, book_imbalance))

        # Signal features (pre-computed, as tournament_engine expects)
        sig_mean_reversion = rng.gauss(0.0, 0.3)
        sig_time_of_day = 1.0 if 3 <= hour <= 6 else -0.5 if 0 <= hour <= 2 else 0.2
        sig_book_imbalance = book_imbalance * 0.8 + rng.gauss(0.0, 0.05)
        sig_wallet_flow = rng.gauss(0.05, 0.2)
        sig_informed_flow = rng.gauss(0.0, 0.25)

        # Outcome: calibrated win rate depends on strategy family
        base_wr = params.get("base_win_rate", 0.52)
        edge_sign = 1 if expected_sign_from_family(family) == "positive" else -1
        local_wr = base_wr + edge_sign * (abs(book_imbalance) * 0.05) + rng.gauss(0.0, 0.05)
        local_wr = max(0.1, min(0.9, local_wr))

        won = rng.random() < local_wr
        if side == "YES":
            outcome = "YES_WON" if won else "NO_WON"
        else:
            outcome = "NO_WON" if won else "YES_WON"

        # Maker fill probability (from BTC5 research: ~10-30% fill rate)
        fill_prob = params.get("maker_fill_prob", 0.20)
        is_filled = rng.random() < fill_prob

        # Days to resolution
        resolution_hours = rng.expovariate(1.0 / 72.0)  # avg 72h
        resolution_hours = max(1.0, min(720.0, resolution_hours))

        # Timestamp (spread over 90 days)
        ts = int(time.time()) - int(rng.uniform(0, 90 * 86400))

        markets.append({
            "condition_id": f"synthetic_{i:06d}",
            "entry_price": round(entry_price, 4),
            "side": side,
            "outcome": outcome,
            "is_filled": is_filled,
            "vpin": round(vpin, 4),
            "spread": round(spread, 4),
            "hour_et": hour,
            "book_imbalance": round(book_imbalance, 4),
            "resolution_hours": round(resolution_hours, 1),
            "timestamp": ts,
            # Signal features for genome compatibility
            "sig_mean_reversion": round(sig_mean_reversion, 4),
            "sig_time_of_day": round(sig_time_of_day, 4),
            "sig_book_imbalance": round(sig_book_imbalance, 4),
            "sig_wallet_flow": round(sig_wallet_flow, 4),
            "sig_informed_flow": round(sig_informed_flow, 4),
            "sig_cross_timeframe": round(rng.gauss(0.0, 0.2), 4),
            "sig_vol_regime": round(rng.gauss(0.0, 0.15), 4),
            "sig_residual_horizon": round(rng.gauss(0.0, 0.2), 4),
            "sig_ml_scanner": round(rng.gauss(0.0, 0.25), 4),
            "sig_indicator_consensus": round(rng.gauss(0.0, 0.2), 4),
            "sig_chainlink_basis": round(rng.gauss(0.0, 0.1), 4),
        })

    return markets


def expected_sign_from_family(family: str) -> str:
    """Return expected alpha sign for a strategy family."""
    negative_families = {"longshot_fade", "sentiment_fade"}
    return "negative" if family in negative_families else "positive"


# ---------------------------------------------------------------------------
# Fee models
# ---------------------------------------------------------------------------


def compute_fee(
    fee_model: str,
    position_usd: float,
    entry_price: float,
    side: str,
) -> float:
    """
    Compute the fee for a single trade.

    Fee models from empirical Polymarket data:
    - maker_rebate: 0% taker fee, 20-25% rebate on spread. Net: small positive.
    - maker_flat: 0% fee (post-only maker, no rebate). Net: 0.
    - taker_flat: ~1.5-3.15% of notional (market order). Net: negative.
    - zero_fee: 0% (Kalshi or sports categories with 0% fee markets).
    """
    if fee_model == "maker_rebate":
        # Maker gets 20-25% of the spread back. Model as 0.0025% of notional.
        return -position_usd * 0.0025  # negative = rebate received
    elif fee_model == "maker_flat":
        return 0.0
    elif fee_model == "taker_flat":
        # Polymarket taker fee: rate=0.02, exponent=1 for prediction markets
        # Crypto markets: rate=0.0044 (0.44%)
        return position_usd * 0.02
    elif fee_model == "zero_fee":
        return 0.0
    else:
        return position_usd * 0.015  # conservative default


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------


class WalkForwardEngine:
    """
    Time-series walk-forward backtester for a single hypothesis.

    Train on [t, t+train_window], test on [t+train, t+train+test_window].
    Slide forward by step_size. Repeat for n_windows windows.

    For each test window, compute:
    - n_trades, gross_pnl, fee_drag, net_pnl
    - win_rate, max_drawdown, sharpe
    - opportunity_density (trades / day in test period)
    - fill_rate (fraction of signals that would have filled as maker)
    """

    def __init__(
        self,
        train_window_days: int = 30,
        test_window_days: int = 10,
        step_size_days: int = 7,
        n_windows: int = 4,
        min_trades_per_window: int = 5,
    ):
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days
        self.step_size_days = step_size_days
        self.n_windows = n_windows
        self.min_trades_per_window = min_trades_per_window

    def run(
        self,
        data: list[dict],
        hypothesis: EdgeHypothesis,
    ) -> list[WalkForwardResult]:
        """
        Run walk-forward evaluation for the hypothesis.

        Returns one WalkForwardResult per window. Windows with < min_trades
        are skipped but counted against the hypothesis (density kill).
        """
        if not data:
            return []

        # Sort by timestamp
        sorted_data = sorted(data, key=lambda m: m.get("timestamp", 0))

        results = []
        train_sec = self.train_window_days * 86400
        test_sec = self.test_window_days * 86400
        step_sec = self.step_size_days * 86400

        t_min = sorted_data[0]["timestamp"]
        t_max = sorted_data[-1]["timestamp"]

        window_start = t_min

        for w in range(self.n_windows):
            train_start = window_start
            train_end = window_start + train_sec
            test_start = train_end
            test_end = test_start + test_sec

            if test_end > t_max:
                break  # Not enough data for this window

            # Test data
            test_data = [
                m for m in sorted_data
                if test_start <= m["timestamp"] < test_end
            ]

            if not test_data:
                window_start += step_sec
                continue

            # Apply hypothesis filters to test data
            signals = self._apply_filters(test_data, hypothesis)

            n_total = len(test_data)
            n_signals = len(signals)

            # Compute fill rate (for maker strategies)
            n_filled = sum(1 for s in signals if s.get("is_filled", True))
            fill_rate = n_filled / n_signals if n_signals > 0 else 0.0

            # For maker, only filled orders generate PnL
            if hypothesis.fee_model in ("maker_rebate", "maker_flat"):
                active_signals = [s for s in signals if s.get("is_filled", True)]
            else:
                active_signals = signals

            n_trades = len(active_signals)

            # Compute PnL
            pnls = []
            gross_wins = 0.0
            gross_losses = 0.0
            position_usd = hypothesis.parameters.get("position_usd", 5.0)

            for sig in active_signals:
                entry_price = sig.get("entry_price", 0.5)
                side = sig.get("side", "YES")
                outcome = sig.get("outcome", "NO_WON")

                won = (side == "YES" and outcome == "YES_WON") or \
                      (side == "NO" and outcome == "NO_WON")

                fee = compute_fee(hypothesis.fee_model, position_usd, entry_price, side)

                if won:
                    payout = position_usd * (1.0 - entry_price) / max(entry_price, 0.01)
                    gross_pnl_trade = payout - fee
                    gross_wins += abs(gross_pnl_trade)
                else:
                    gross_pnl_trade = -position_usd - fee
                    gross_losses += abs(gross_pnl_trade)

                pnls.append(gross_pnl_trade)

            # Aggregate metrics
            total_gross = sum(pnls) if pnls else 0.0
            total_fee = sum(
                compute_fee(hypothesis.fee_model, position_usd,
                            s.get("entry_price", 0.5), s.get("side", "YES"))
                for s in active_signals
            )
            total_net = total_gross  # fee already embedded in pnls above

            win_rate = sum(1 for p in pnls if p > 0) / n_trades if n_trades > 0 else 0.0

            # Max drawdown
            max_dd = _compute_max_drawdown(pnls)

            # Sharpe (daily)
            sharpe = _compute_sharpe(pnls)

            # Opportunity density
            test_days = self.test_window_days or 1
            opp_density = n_signals / test_days

            results.append(WalkForwardResult(
                window_index=w,
                train_start=int(train_start),
                train_end=int(train_end),
                test_start=int(test_start),
                test_end=int(test_end),
                n_trades=n_trades,
                gross_pnl=round(total_gross, 4),
                fee_drag=round(abs(total_fee), 4),
                net_pnl=round(total_net, 4),
                win_rate=round(win_rate, 4),
                max_drawdown=round(max_dd, 4),
                sharpe=round(sharpe, 4),
                opportunity_density=round(opp_density, 4),
                fill_rate=round(fill_rate, 4),
            ))

            window_start += step_sec

        return results

    def _apply_filters(
        self,
        data: list[dict],
        hypothesis: EdgeHypothesis,
    ) -> list[dict]:
        """Apply hypothesis-specific entry filters to market data."""
        params = hypothesis.parameters
        family = hypothesis.strategy_family
        signals = []

        for market in data:
            # VPIN filter (toxicity gate)
            max_vpin = params.get("max_vpin", 0.60)
            if market.get("vpin", 0.0) > max_vpin:
                continue

            # Spread filter
            spread = market.get("spread", 0.05)
            min_spread = params.get("min_spread", 0.01)
            max_spread = params.get("max_spread", 0.20)
            if not (min_spread <= spread <= max_spread):
                continue

            # Price filter
            price = market.get("entry_price", 0.5)
            min_price = params.get("min_entry_price", 0.05)
            max_price = params.get("max_entry_price", 0.95)
            if not (min_price <= price <= max_price):
                continue

            # Hour filter
            hour = market.get("hour_et", 12)
            hour_start = params.get("hour_start_et", 0)
            hour_end = params.get("hour_end_et", 23)
            if hour_start <= hour_end:
                if not (hour_start <= hour <= hour_end):
                    continue
            else:  # wrap-around
                if not (hour >= hour_start or hour <= hour_end):
                    continue

            # Side filter (for directional strategies)
            side_filter = params.get("side_filter", "both")
            market_side = market.get("side", "YES")
            if side_filter == "YES" and market_side != "YES":
                continue
            if side_filter == "NO" and market_side != "NO":
                continue

            # Family-specific filters
            if family == "longshot_fade":
                # Trade NO on high-price YES markets (longshot bias)
                if price < params.get("longshot_threshold", 0.80):
                    continue
                # Override side
                market = dict(market)
                market["side"] = "NO"
                market["entry_price"] = 1.0 - price

            elif family == "maker_micro":
                # Maker requires spread > threshold for rebate
                if spread < params.get("maker_min_spread", 0.02):
                    continue

            elif family == "time_decay":
                # Only near-expiry markets
                max_hours = params.get("max_hours_to_expiry", 48.0)
                if market.get("resolution_hours", 9999) > max_hours:
                    continue

            signals.append(market)

        return signals


# ---------------------------------------------------------------------------
# Bayesian kill rules
# ---------------------------------------------------------------------------


def _compute_max_drawdown(pnls: list[float]) -> float:
    """Compute max drawdown from a sequence of P&L values."""
    if not pnls:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        if peak > 0:
            dd = (peak - cumulative) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _compute_sharpe(pnls: list[float]) -> float:
    """Annualized Sharpe from trade-level P&L."""
    n = len(pnls)
    if n < 2:
        return 0.0
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / n
    std = math.sqrt(var) if var > 0 else 0.001
    return (mean / std) * math.sqrt(252)


def _log_growth_posterior(
    pnls: list[float],
    position_usd: float = 5.0,
) -> dict:
    """
    Compute LogGrowthPosterior stats from trade-level P&L.

    Imports from bot.bayesian_promoter if available; otherwise implements
    the conjugate update inline for subprocess compatibility.
    """
    try:
        # Use the canonical implementation
        sys.path.insert(0, str(_REPO_ROOT))
        from bot.bayesian_promoter import LogGrowthPosterior
        posterior = LogGrowthPosterior()
        for pnl in pnls:
            log_ret = math.log(1.0 + max(-0.99, pnl / max(position_usd, 1.0)))
            posterior.update(log_ret)
        return posterior.to_dict()
    except ImportError:
        # Inline implementation (subprocess fallback)
        return _log_growth_posterior_inline(pnls, position_usd)


def _log_growth_posterior_inline(
    pnls: list[float],
    position_usd: float = 5.0,
) -> dict:
    """Inline conjugate Normal-InverseGamma posterior for log returns."""
    mu_0, kappa_0, alpha_0, beta_0 = 0.0, 1.0, 2.0, 0.01

    log_returns = [
        math.log(1.0 + max(-0.99, p / max(position_usd, 1.0)))
        for p in pnls
    ]

    n = len(log_returns)
    if n == 0:
        return {"n": 0, "posterior_mean": 0.0, "prob_positive": 0.5,
                "credible_interval_90": [-0.1, 0.1]}

    x_bar = sum(log_returns) / n
    kappa_n = kappa_0 + n
    mu_n = (kappa_0 * mu_0 + n * x_bar) / kappa_n
    alpha_n = alpha_0 + n / 2.0
    ss = sum((x - x_bar) ** 2 for x in log_returns)
    beta_n = (
        beta_0
        + 0.5 * ss
        + 0.5 * (kappa_0 * n / kappa_n) * (x_bar - mu_0) ** 2
    )

    scale = math.sqrt(beta_n / (alpha_n * kappa_n)) if alpha_n > 0 and kappa_n > 0 else 1.0
    nu = 2.0 * alpha_n

    # P(mu > 0) via Student-t CDF
    if scale < 1e-12:
        p_pos = 1.0 if mu_n > 0 else 0.0
    else:
        t_stat = mu_n / scale
        p_pos = _student_t_cdf_inline(t_stat, nu)

    # 90% credible interval
    z = 1.645
    correction = math.sqrt(nu / (nu - 2)) if nu > 2 else 3.0
    half_width = z * scale * correction
    ci = [mu_n - half_width, mu_n + half_width]

    return {
        "n": n,
        "posterior_mean": round(mu_n, 8),
        "posterior_scale": round(scale, 8),
        "posterior_df": round(nu, 2),
        "prob_positive": round(p_pos, 6),
        "credible_interval_90": [round(ci[0], 8), round(ci[1], 8)],
    }


def _student_t_cdf_inline(t: float, nu: float) -> float:
    """Student-t CDF (inline, no scipy)."""
    if nu <= 0:
        return 0.5
    x = nu / (nu + t * t)
    ib = _reg_incomplete_beta(x, nu / 2.0, 0.5)
    if t >= 0:
        return 1.0 - 0.5 * ib
    else:
        return 0.5 * ib


def _reg_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta via continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _reg_incomplete_beta(1.0 - x, b, a)
    ln_prefix = (
        a * math.log(x) + b * math.log(1.0 - x)
        - math.log(a)
        - (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))
    )
    cf = _beta_cf_inline(x, a, b)
    return min(1.0, max(0.0, math.exp(ln_prefix) * cf))


def _beta_cf_inline(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """Lentz continued fraction for incomplete beta."""
    tiny = 1e-30
    f = 1.0 + tiny
    c = f
    d = 0.0
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        c = 1.0 + num / c
        if abs(c) < tiny:
            c = tiny
        f *= c * d
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + num * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        c = 1.0 + num / c
        if abs(c) < tiny:
            c = tiny
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < 1e-12:
            return f
    return f


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR correction
# ---------------------------------------------------------------------------


def benjamini_hochberg(p_values: list[float], alpha: float = 0.10) -> list[bool]:
    """
    Benjamini-Hochberg FDR correction for multiple testing.

    Returns a list of booleans: True if hypothesis i survives FDR correction.
    The BH procedure controls the false discovery rate at level alpha.
    """
    n = len(p_values)
    if n == 0:
        return []

    # Sort by p-value
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    reject = [False] * n

    # Find largest k such that p_(k) <= (k/n) * alpha
    for rank, (orig_idx, p) in enumerate(indexed, start=1):
        threshold = (rank / n) * alpha
        if p <= threshold:
            # All hypotheses up to this rank are rejected (FDR controlled)
            for r2, (idx2, _) in enumerate(indexed[:rank], start=1):
                reject[idx2] = True

    return reject


# ---------------------------------------------------------------------------
# Single-hypothesis evaluator (runs in subprocess)
# ---------------------------------------------------------------------------


def _evaluate_hypothesis_worker(args: tuple) -> dict:
    """
    Worker for parallel hypothesis evaluation.

    Takes (hypothesis_dict, data_path, config) and returns a result dict.
    Must be self-contained for pickle compatibility.
    """
    import sys
    import os
    repo_root = os.environ.get("ELASTIFUND_ROOT", str(Path(__file__).parent.parent))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    hyp_dict, data_path, config = args
    t0 = time.monotonic()

    try:
        result = _run_hypothesis_evaluation(hyp_dict, data_path, config)
    except Exception as e:
        result = {
            "hypothesis_id": hyp_dict.get("hypothesis_id", "unknown"),
            "error": str(e)[:300],
            "windows": [],
            "posterior_dict": {"n": 0, "prob_positive": 0.5, "posterior_mean": 0.0},
            "prob_positive": 0.5,
            "kill_reason": f"eval_error: {str(e)[:200]}",
            "is_survivor": False,
            "total_simulated_trades": 0,
            "avg_net_pnl_per_window": 0.0,
            "opportunity_density_per_day": 0.0,
            "max_drawdown": 1.0,
            "net_edge_positive": False,
            "fee_stress_survives": False,
            "density_ok": False,
            "fill_rate_ok": False,
            "drawdown_ok": False,
            "bh_fdr_passes": False,
        }

    result["eval_time_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return result


def _run_hypothesis_evaluation(hyp_dict: dict, data_path: str, config: dict) -> dict:
    """Core walk-forward evaluation for one hypothesis."""
    import sys
    import os
    repo_root = os.environ.get("ELASTIFUND_ROOT", str(Path(__file__).parent.parent))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    hyp_id = hyp_dict["hypothesis_id"]
    family = hyp_dict["strategy_family"]
    params = hyp_dict["parameters"]
    fee_model = hyp_dict["fee_model"]
    venue = hyp_dict["venue"]

    # Load or generate data
    data = _load_market_data(data_path, family, params)

    # Reconstruct a minimal EdgeHypothesis for the walk-forward engine
    from dataclasses import dataclass, field as dc_field
    from datetime import datetime, timezone

    # We can't easily reconstruct the full dataclass across processes,
    # so pass parameters directly to the engine
    engine_config = {
        "train_window_days": config.get("train_window_days", 30),
        "test_window_days": config.get("test_window_days", 10),
        "step_size_days": config.get("step_size_days", 7),
        "n_windows": config.get("n_windows", 4),
    }

    # Inline walk-forward (avoid dataclass reconstruction in subprocess)
    windows = _run_walk_forward_inline(data, hyp_dict, engine_config)

    # Aggregate metrics
    all_pnls = []
    all_densities = []
    all_fill_rates = []
    all_drawdowns = []
    all_fee_drags = []

    for w in windows:
        # Reconstruct per-trade PnL list from window aggregates
        # (we store aggregated metrics, not individual trades, for efficiency)
        for _ in range(max(0, w["n_trades"])):
            # Approximate individual trade PnL from window stats
            pnl_per_trade = w["net_pnl"] / max(1, w["n_trades"])
            all_pnls.append(pnl_per_trade)
        all_densities.append(w["opportunity_density"])
        all_fill_rates.append(w["fill_rate"])
        all_drawdowns.append(w["max_drawdown"])
        all_fee_drags.append(w["fee_drag"])

    total_trades = sum(w["n_trades"] for w in windows)
    position_usd = params.get("position_usd", 5.0)
    posterior_dict = _log_growth_posterior_inline(all_pnls, position_usd)

    prob_positive = posterior_dict.get("prob_positive", 0.5)
    posterior_mean = posterior_dict.get("posterior_mean", 0.0)

    avg_density = sum(all_densities) / len(all_densities) if all_densities else 0.0
    avg_fill_rate = sum(all_fill_rates) / len(all_fill_rates) if all_fill_rates else 0.0
    max_dd = max(all_drawdowns) if all_drawdowns else 0.0
    total_net_pnl = sum(w["net_pnl"] for w in windows)
    avg_net_pnl = total_net_pnl / len(windows) if windows else 0.0
    avg_fee_drag = sum(all_fee_drags) / len(all_fee_drags) if all_fee_drags else 0.0
    total_gross = sum(w["gross_pnl"] for w in windows)

    # --- Kill rule evaluation ---
    kill_reason = None

    # Kill 1: Net edge kill — P(mu > 0) < 0.30 with sufficient data
    if total_trades >= 30 and prob_positive < 0.30:
        kill_reason = f"net_edge_kill: P(mu>0)={prob_positive:.3f} < 0.30 at n={total_trades}"

    # Kill 2: Fee kill — fee drag > 50% of gross edge
    if kill_reason is None:
        gross_edge = abs(total_gross)
        if gross_edge > 0 and avg_fee_drag > 0.5 * gross_edge / max(len(windows), 1):
            kill_reason = (
                f"fee_kill: avg_fee_drag={avg_fee_drag:.3f} > "
                f"50% of gross_edge={gross_edge:.3f}"
            )

    # Kill 3: Density kill — < 1 opportunity per day
    if kill_reason is None and avg_density < 1.0 and len(windows) >= 2:
        kill_reason = f"density_kill: avg_density={avg_density:.2f} opp/day < 1.0"

    # Kill 4: Fill kill — P(fill) < 10% for maker strategies
    if kill_reason is None:
        if fee_model in ("maker_rebate", "maker_flat") and avg_fill_rate < 0.10:
            kill_reason = f"fill_kill: avg_fill_rate={avg_fill_rate:.3f} < 0.10"

    # Kill 5: Drawdown kill — max DD > 3x avg daily PnL
    if kill_reason is None:
        avg_daily_pnl = avg_net_pnl / max(engine_config["test_window_days"], 1)
        if avg_daily_pnl > 0 and max_dd > 3 * avg_daily_pnl:
            kill_reason = (
                f"drawdown_kill: max_dd={max_dd:.3f} > "
                f"3x avg_daily_pnl={avg_daily_pnl:.4f}"
            )

    # --- Promotion criteria ---
    net_edge_positive = avg_net_pnl > 0 and posterior_mean > 0
    fee_stress_survives = _check_fee_stress(windows, fee_model, params)
    density_ok = avg_density >= 2.0
    fill_rate_ok = avg_fill_rate >= 0.20 if fee_model in ("maker_rebate", "maker_flat") else True
    drawdown_ok = max_dd <= 0.30  # proxy for 3x daily check

    # BH-FDR: approximate p-value from the posterior
    # P-value = P(we see this data or more extreme | mu=0)
    # We approximate this as (1 - prob_positive) for the one-sided test
    approx_p_value = 1.0 - prob_positive

    n_surviving_windows = len([w for w in windows if w["net_pnl"] > 0])

    is_survivor = (
        kill_reason is None
        and prob_positive >= 0.90
        and net_edge_positive
        and fee_stress_survives
        and density_ok
        and fill_rate_ok
        and drawdown_ok
        and n_surviving_windows >= 3
        and total_trades >= 30
    )

    return {
        "hypothesis_id": hyp_id,
        "windows": windows,
        "posterior_dict": posterior_dict,
        "prob_positive": round(prob_positive, 6),
        "kill_reason": kill_reason,
        "is_survivor": is_survivor,
        "total_simulated_trades": total_trades,
        "avg_net_pnl_per_window": round(avg_net_pnl, 4),
        "opportunity_density_per_day": round(avg_density, 4),
        "max_drawdown": round(max_dd, 4),
        "net_edge_positive": net_edge_positive,
        "fee_stress_survives": fee_stress_survives,
        "density_ok": density_ok,
        "fill_rate_ok": fill_rate_ok,
        "drawdown_ok": drawdown_ok,
        "bh_fdr_passes": True,  # Updated in main engine with BH across batch
        "approx_p_value": round(approx_p_value, 6),
        "n_surviving_windows": n_surviving_windows,
    }


def _run_walk_forward_inline(
    data: list[dict],
    hyp_dict: dict,
    config: dict,
) -> list[dict]:
    """Inline walk-forward (subprocess-safe, no dataclass dependency)."""
    if not data:
        return []

    params = hyp_dict["parameters"]
    family = hyp_dict["strategy_family"]
    fee_model = hyp_dict["fee_model"]
    position_usd = params.get("position_usd", 5.0)

    train_sec = config["train_window_days"] * 86400
    test_sec = config["test_window_days"] * 86400
    step_sec = config["step_size_days"] * 86400
    n_windows = config["n_windows"]

    sorted_data = sorted(data, key=lambda m: m.get("timestamp", 0))
    t_min = sorted_data[0]["timestamp"]
    t_max = sorted_data[-1]["timestamp"]

    window_start = t_min
    results = []

    for w in range(n_windows):
        test_start = window_start + train_sec
        test_end = test_start + test_sec

        if test_end > t_max:
            break

        test_data = [
            m for m in sorted_data
            if test_start <= m.get("timestamp", 0) < test_end
        ]

        if not test_data:
            window_start += step_sec
            continue

        # Apply filters inline
        signals = _apply_filters_inline(test_data, params, family)
        n_signals = len(signals)

        # Maker fill filter
        n_filled = sum(1 for s in signals if s.get("is_filled", True))
        fill_rate = n_filled / n_signals if n_signals > 0 else 0.0

        if fee_model in ("maker_rebate", "maker_flat"):
            active = [s for s in signals if s.get("is_filled", True)]
        else:
            active = signals

        n_trades = len(active)
        pnls = []
        gross_wins = 0.0
        gross_losses = 0.0
        total_fee = 0.0

        for sig in active:
            entry_price = sig.get("entry_price", 0.5)
            side = sig.get("side", "YES")
            outcome = sig.get("outcome", "NO_WON")

            won = (side == "YES" and outcome == "YES_WON") or \
                  (side == "NO" and outcome == "NO_WON")

            fee = _compute_fee_inline(fee_model, position_usd)
            total_fee += abs(fee)

            if won:
                payout = position_usd * (1.0 - entry_price) / max(entry_price, 0.01)
                pnl = payout - abs(fee) if fee > 0 else payout + abs(fee)
                gross_wins += abs(pnl)
            else:
                pnl = -position_usd - (fee if fee > 0 else 0)
                gross_losses += abs(pnl)

            pnls.append(pnl)

        total_gross = gross_wins - gross_losses
        total_net = sum(pnls)
        win_rate = sum(1 for p in pnls if p > 0) / n_trades if n_trades > 0 else 0.0
        max_dd = _compute_max_drawdown(pnls)
        sharpe = _compute_sharpe(pnls)
        test_days = config["test_window_days"] or 1
        opp_density = n_signals / test_days

        results.append({
            "window_index": w,
            "train_start": int(window_start),
            "train_end": int(window_start + train_sec),
            "test_start": int(test_start),
            "test_end": int(test_end),
            "n_trades": n_trades,
            "gross_pnl": round(total_gross, 4),
            "fee_drag": round(total_fee, 4),
            "net_pnl": round(total_net, 4),
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_dd, 4),
            "sharpe": round(sharpe, 4),
            "opportunity_density": round(opp_density, 4),
            "fill_rate": round(fill_rate, 4),
        })

        window_start += step_sec

    return results


def _apply_filters_inline(data: list[dict], params: dict, family: str) -> list[dict]:
    """Inline filter application (subprocess-safe)."""
    signals = []
    for market in data:
        vpin = market.get("vpin", 0.0)
        if vpin > params.get("max_vpin", 0.60):
            continue

        spread = market.get("spread", 0.05)
        if not (params.get("min_spread", 0.01) <= spread <= params.get("max_spread", 0.20)):
            continue

        price = market.get("entry_price", 0.5)
        if not (params.get("min_entry_price", 0.05) <= price <= params.get("max_entry_price", 0.95)):
            continue

        hour = market.get("hour_et", 12)
        h_start = params.get("hour_start_et", 0)
        h_end = params.get("hour_end_et", 23)
        if h_start <= h_end:
            if not (h_start <= hour <= h_end):
                continue
        else:
            if not (hour >= h_start or hour <= h_end):
                continue

        side_filter = params.get("side_filter", "both")
        market_side = market.get("side", "YES")
        if side_filter == "YES" and market_side != "YES":
            continue
        if side_filter == "NO" and market_side != "NO":
            continue

        if family == "longshot_fade":
            threshold = params.get("longshot_threshold", 0.80)
            if price < threshold:
                continue
            market = dict(market)
            market["side"] = "NO"
            market["entry_price"] = round(1.0 - price, 4)

        elif family == "time_decay":
            if market.get("resolution_hours", 9999) > params.get("max_hours_to_expiry", 48.0):
                continue

        elif family == "maker_micro":
            if spread < params.get("maker_min_spread", 0.02):
                continue

        signals.append(market)
    return signals


def _compute_fee_inline(fee_model: str, position_usd: float) -> float:
    """Inline fee computation."""
    if fee_model == "maker_rebate":
        return -position_usd * 0.0025
    elif fee_model == "maker_flat":
        return 0.0
    elif fee_model == "taker_flat":
        return position_usd * 0.02
    elif fee_model == "zero_fee":
        return 0.0
    return position_usd * 0.015


def _check_fee_stress(
    windows: list[dict],
    fee_model: str,
    params: dict,
) -> bool:
    """Check if the strategy is profitable under 2x fee stress."""
    if not windows:
        return False
    position_usd = params.get("position_usd", 5.0)
    stress_fee = _compute_fee_inline(fee_model, position_usd) * 2.0
    # Recompute net PnL with doubled fees
    total_stressed_net = sum(
        w["net_pnl"] - (abs(stress_fee) * w["n_trades"])
        for w in windows
    )
    return total_stressed_net > 0


def _load_market_data(data_path: str, family: str, params: dict) -> list[dict]:
    """Load historical market data, or generate synthetic if unavailable."""
    path = Path(data_path) if data_path else None

    if path and path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            if data:
                return data
        except (json.JSONDecodeError, IOError):
            pass

    # No data available — generate synthetic
    n_markets = 600  # enough for 4 walk-forward windows of 30-day train + 10-day test
    return _generate_synthetic_market_data(
        n_markets=n_markets,
        seed=hash(family + str(params)) % (2 ** 31),
        family=family,
        parameters=params,
    )


# ---------------------------------------------------------------------------
# Hypothesis generators
# ---------------------------------------------------------------------------


class HypothesisGenerator:
    """
    Three complementary methods for generating testable hypotheses.

    1. Parameter sweep: enumerate parameter grids for known strategy families.
    2. Combinatorial feature selection: mix signal sources with entry/exit templates.
    3. Research-driven seeding: parse edge_backlog_ranked.md for untested ideas.
    """

    STRATEGY_FAMILIES = [
        "longshot_fade",
        "latency_capture",
        "maker_micro",
        "structural_basket",
        "time_decay",
        "cross_platform_arb",
        "sentiment_fade",
        "data_release",
        "combinatorial",
    ]

    VENUES = ["polymarket", "kalshi"]

    FEE_MODELS_BY_VENUE = {
        "polymarket": ["maker_rebate", "maker_flat", "taker_flat"],
        "kalshi": ["zero_fee", "taker_flat"],
        "alpaca": ["zero_fee"],
    }

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._seen_fingerprints: set[str] = set()

    def generate_all(
        self,
        max_hypotheses: int = 50,
        backlog_path: Optional[str] = None,
        strategies_dir: Optional[str] = None,
    ) -> list[EdgeHypothesis]:
        """Generate up to max_hypotheses unique hypotheses using all three methods."""
        hypotheses: list[EdgeHypothesis] = []
        seen: set[str] = set()

        # Allocate budget across three sources
        n_sweep = max_hypotheses // 3
        n_combo = max_hypotheses // 3
        n_research = max_hypotheses - n_sweep - n_combo

        # Method 1: Parameter sweep
        for h in self._parameter_sweep(n_sweep, strategies_dir):
            fp = h.fingerprint
            if fp not in seen:
                seen.add(fp)
                hypotheses.append(h)

        # Method 2: Combinatorial
        for h in self._combinatorial_features(n_combo):
            fp = h.fingerprint
            if fp not in seen:
                seen.add(fp)
                hypotheses.append(h)

        # Method 3: Research-driven
        for h in self._research_seeded(n_research, backlog_path):
            fp = h.fingerprint
            if fp not in seen:
                seen.add(fp)
                hypotheses.append(h)

        logger.info(
            "Generated %d hypotheses: %d sweep, %d combo, %d research",
            len(hypotheses), n_sweep, n_combo, n_research,
        )
        return hypotheses[:max_hypotheses]

    def _parameter_sweep(
        self,
        n: int,
        strategies_dir: Optional[str] = None,
    ) -> list[EdgeHypothesis]:
        """
        Enumerate parameter grids across strategy families.

        For each family, sweep:
        - time filters (hour windows): morning, daytime, evening, overnight
        - side: YES-only, NO-only, both
        - venue: polymarket, kalshi
        - longshot threshold: 0.75, 0.80, 0.85, 0.90
        - max VPIN: 0.40, 0.55, 0.70
        """
        now = datetime.now(timezone.utc)
        hypotheses = []

        # Time windows (ET hours)
        time_windows = [
            (3, 6, "early_morning"),
            (7, 11, "morning"),
            (12, 16, "afternoon"),
            (17, 21, "evening"),
            (22, 2, "overnight"),
            (0, 23, "all_day"),
        ]

        families_to_sweep = [
            "longshot_fade", "maker_micro", "time_decay", "latency_capture"
        ]

        for family in families_to_sweep:
            for venue in self.VENUES:
                fee_model = self.rng.choice(self.FEE_MODELS_BY_VENUE.get(venue, ["taker_flat"]))

                for h_start, h_end, window_name in time_windows:
                    for side in ["both", "NO", "YES"]:
                        params = {
                            "hour_start_et": h_start,
                            "hour_end_et": h_end,
                            "side_filter": side,
                            "max_vpin": self.rng.choice([0.40, 0.55, 0.70]),
                            "position_usd": 5.0,
                            "min_entry_price": 0.05,
                            "max_entry_price": 0.95,
                            "min_spread": 0.01,
                            "max_spread": 0.20,
                        }

                        if family == "longshot_fade":
                            params["longshot_threshold"] = self.rng.choice([0.75, 0.80, 0.85, 0.90])
                            params["min_entry_price"] = params["longshot_threshold"]
                            params["side_filter"] = "NO"  # Always fade via NO

                        elif family == "time_decay":
                            params["max_hours_to_expiry"] = self.rng.choice([12.0, 24.0, 48.0])

                        elif family == "maker_micro":
                            params["maker_min_spread"] = self.rng.choice([0.02, 0.03, 0.05])
                            params["maker_fill_prob"] = 0.20

                        hyp_id = f"SWEEP_{family}_{venue}_{window_name}_{side}"

                        h = EdgeHypothesis(
                            hypothesis_id=hyp_id,
                            strategy_family=family,
                            venue=venue,
                            parameters=params,
                            entry_logic=(
                                f"Enter {side} positions in {family} "
                                f"during {window_name} ET hours on {venue}"
                            ),
                            exit_logic="Exit at resolution or TTL expiry",
                            fee_model=fee_model,
                            expected_sign=expected_sign_from_family(family),
                            kill_conditions=[
                                "net_edge_kill: P(mu>0) < 0.30 after 30 trades",
                                "fee_kill: fee_drag > 50% gross_edge",
                                "density_kill: < 1 opp/day",
                            ],
                            created_at=now,
                            status="pending",
                        )

                        hypotheses.append(h)
                        if len(hypotheses) >= n:
                            return hypotheses

        return hypotheses[:n]

    def _combinatorial_features(self, n: int) -> list[EdgeHypothesis]:
        """
        Combinatorial mixing of signal sources and entry templates.

        Signal sources (from src/strategies/):
        - mean_reversion, book_imbalance, informed_flow, wallet_flow,
          time_of_day, vol_regime, cross_timeframe, chainlink_basis,
          ml_scanner, indicator_consensus, residual_horizon

        Entry templates:
        - "high_agreement": require >= 3 signals pointing same direction
        - "single_strong": one signal with confidence > 0.70
        - "consensus_fade": fade when >= 4 signals disagree with price
        """
        now = datetime.now(timezone.utc)
        hypotheses = []

        signal_sources = [
            "mean_reversion", "book_imbalance", "informed_flow",
            "wallet_flow", "time_of_day", "vol_regime", "cross_timeframe",
            "chainlink_basis", "ml_scanner", "indicator_consensus",
        ]

        entry_templates = [
            ("high_agreement", "Enter when >= 3 signal sources agree (> 0.60 weighted consensus)"),
            ("single_strong", "Enter when primary signal confidence > 0.70"),
            ("consensus_fade", "Fade price when >= 4 sources disagree with current direction"),
        ]

        for template_name, template_desc in entry_templates:
            for k in [2, 3, 4]:  # Number of signal sources to combine
                # Sample k-combinations from signal_sources
                for attempt in range(n // (len(entry_templates) * 3) + 1):
                    combo = sorted(self.rng.sample(signal_sources, min(k, len(signal_sources))))
                    venue = self.rng.choice(self.VENUES)
                    fee_model = self.rng.choice(self.FEE_MODELS_BY_VENUE[venue])

                    params = {
                        "signal_sources": combo,
                        "entry_template": template_name,
                        "min_signals_active": k,
                        "signal_agreement_pct": self.rng.choice([0.55, 0.65, 0.75]),
                        "min_confidence": self.rng.choice([0.55, 0.60, 0.65]),
                        "max_vpin": 0.60,
                        "position_usd": 5.0,
                        "min_entry_price": 0.05,
                        "max_entry_price": 0.95,
                        "min_spread": 0.01,
                        "max_spread": 0.20,
                        "hour_start_et": 0,
                        "hour_end_et": 23,
                        "side_filter": "both",
                    }

                    combo_str = "_".join(s[:4] for s in combo)
                    hyp_id = f"COMBO_{template_name}_{k}sig_{combo_str}_{venue}"

                    h = EdgeHypothesis(
                        hypothesis_id=hyp_id,
                        strategy_family="combinatorial",
                        venue=venue,
                        parameters=params,
                        entry_logic=f"{template_desc} using: {', '.join(combo)}",
                        exit_logic="Exit at resolution",
                        fee_model=fee_model,
                        expected_sign="positive",
                        kill_conditions=[
                            "net_edge_kill: P(mu>0) < 0.30 after 30 trades",
                            "fee_kill: fee_drag > 50% gross_edge",
                            "fill_kill: fill_rate < 10% for maker",
                        ],
                        created_at=now,
                        status="pending",
                    )

                    hypotheses.append(h)
                    if len(hypotheses) >= n:
                        return hypotheses

        return hypotheses[:n]

    def _research_seeded(
        self,
        n: int,
        backlog_path: Optional[str] = None,
    ) -> list[EdgeHypothesis]:
        """
        Parse edge_backlog_ranked.md and seed hypotheses from untested strategies.

        Extracts: strategy name, composite score, P(works), mechanism.
        Converts each to a testable hypothesis with realistic parameters.
        """
        now = datetime.now(timezone.utc)
        hypotheses = []

        # Parse the backlog
        entries = self._parse_backlog(backlog_path)

        # Convert top entries to hypotheses
        for entry in entries:
            if len(hypotheses) >= n:
                break

            name = entry.get("name", "unknown")
            mechanism = entry.get("mechanism", "")
            composite = float(entry.get("composite", 3.0))
            p_works = float(entry.get("p_works", 0.25))

            # Only seed hypotheses with P(works) >= 15% and composite >= 3.0
            if p_works < 0.15 or composite < 3.0:
                continue

            # Map to strategy family
            family = self._classify_family(mechanism, name)
            venue = "polymarket"
            fee_model = "maker_rebate"

            # Build parameters from mechanism
            params = self._mechanism_to_params(mechanism, name, composite)
            params["position_usd"] = 5.0
            params["p_works_prior"] = p_works
            params["composite_score"] = composite

            hyp_id = f"RESEARCH_{re.sub(r'[^a-zA-Z0-9]', '_', name[:40])}"

            h = EdgeHypothesis(
                hypothesis_id=hyp_id,
                strategy_family=family,
                venue=venue,
                parameters=params,
                entry_logic=f"Research-seeded: {mechanism[:200]}",
                exit_logic="Exit at resolution or 48h TTL",
                fee_model=fee_model,
                expected_sign="positive",
                kill_conditions=[
                    "net_edge_kill: P(mu>0) < 0.30 after 30 trades",
                    f"prior_p_works: {p_works:.2f} — kill fast if data contradicts",
                    "density_kill: < 1 opp/day",
                ],
                created_at=now,
                status="pending",
            )

            hypotheses.append(h)

        # Pad with parameter-swept research hypotheses if backlog is short
        if len(hypotheses) < n:
            extras = self._parameter_sweep(n - len(hypotheses))
            for h in extras:
                if len(hypotheses) >= n:
                    break
                h.hypothesis_id = f"RESEARCH_FALLBACK_{h.hypothesis_id}"
                hypotheses.append(h)

        return hypotheses[:n]

    def _parse_backlog(self, backlog_path: Optional[str]) -> list[dict]:
        """Parse edge_backlog_ranked.md for hypothesis seeding."""
        if not backlog_path:
            # Try canonical path
            backlog_path = str(_REPO_ROOT / "research" / "edge_backlog_ranked.md")

        try:
            content = Path(backlog_path).read_text()
        except (FileNotFoundError, IOError):
            logger.warning("Could not read backlog at %s", backlog_path)
            return []

        entries = []
        # Parse table rows: | Rank | Strategy ID | Name | P(Works) | Composite | ... |
        # and also: | Rank | Edge Name | Category | Mechanism | Composite | ... |
        table_row = re.compile(
            r"\|\s*(?P<rank>\d+[*]?)\s*\|\s*(?P<id>[A-Z0-9-]+)?\s*\|"
            r"\s*(?P<name>[^|]+?)\s*\|\s*(?P<p_works>\d+%?)\s*\|"
            r"\s*(?P<composite>[\d.]+)\s*\|"
        )
        simple_row = re.compile(
            r"\|\s*\d+\s*\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<category>[^|]+?)\s*\|"
            r"\s*(?P<mechanism>[^|]+?)\s*\|\s*(?P<composite>[\d.]+)\s*\|"
        )

        for line in content.splitlines():
            if not line.startswith("|"):
                continue
            # Skip header and separator lines
            if "---" in line or "Rank" in line or "Strategy" in line:
                continue

            m = table_row.match(line)
            if m:
                p_str = m.group("p_works").strip().rstrip("%")
                try:
                    p_works = float(p_str) / 100 if float(p_str) > 1 else float(p_str)
                except ValueError:
                    p_works = 0.25

                entries.append({
                    "name": m.group("name").strip(),
                    "mechanism": m.group("name").strip(),  # use name as mechanism fallback
                    "composite": m.group("composite").strip(),
                    "p_works": p_works,
                })
                continue

            m2 = simple_row.match(line)
            if m2:
                try:
                    composite = float(m2.group("composite").strip())
                except ValueError:
                    composite = 3.0
                entries.append({
                    "name": m2.group("name").strip(),
                    "mechanism": m2.group("mechanism").strip(),
                    "composite": composite,
                    "p_works": 0.30,  # default when not specified
                })

        # Sort by composite score descending
        entries.sort(key=lambda e: float(e.get("composite", 0)), reverse=True)
        return entries

    def _classify_family(self, mechanism: str, name: str) -> str:
        """Classify a research entry into a strategy family."""
        text = (mechanism + " " + name).lower()
        if any(w in text for w in ["longshot", "favorite", "bias", "fade"]):
            return "longshot_fade"
        if any(w in text for w in ["maker", "rebate", "post-only", "spread"]):
            return "maker_micro"
        if any(w in text for w in ["decay", "expiry", "theta", "near"]):
            return "time_decay"
        if any(w in text for w in ["arb", "divergence", "kalshi", "cross-platform"]):
            return "cross_platform_arb"
        if any(w in text for w in ["sentiment", "contrarian", "retail"]):
            return "sentiment_fade"
        if any(w in text for w in ["data", "release", "fred", "bls", "government"]):
            return "data_release"
        if any(w in text for w in ["latency", "speed", "fast"]):
            return "latency_capture"
        return "structural_basket"

    def _mechanism_to_params(
        self,
        mechanism: str,
        name: str,
        composite: float,
    ) -> dict:
        """Convert a mechanism description to hypothesis parameters."""
        text = (mechanism + " " + name).lower()
        params: dict = {
            "max_vpin": 0.60,
            "min_spread": 0.01,
            "max_spread": 0.20,
            "min_entry_price": 0.05,
            "max_entry_price": 0.95,
            "hour_start_et": 0,
            "hour_end_et": 23,
            "side_filter": "both",
        }

        # Longshot parameters
        if "longshot" in text or "favorite" in text or "fade" in text:
            params["longshot_threshold"] = 0.82
            params["max_entry_price"] = 0.95
            params["side_filter"] = "NO"

        # Time-of-day
        if "morning" in text or "early" in text:
            params["hour_start_et"] = 3
            params["hour_end_et"] = 8

        # Near-expiry
        if "expiry" in text or "theta" in text or "decay" in text:
            params["max_hours_to_expiry"] = 24.0

        # NO-side bias (from Polymarket research: NO outperforms YES)
        if "no-side" in text or "no side" in text:
            params["side_filter"] = "NO"

        return params


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class EdgeDiscoveryEngine:
    """
    Continuous edge discovery daemon.

    Orchestrates the full discovery cycle:
    1. Generate hypotheses (3 methods)
    2. Evaluate each via walk-forward (parallel)
    3. Apply kill rules
    4. Apply BH-FDR correction
    5. Surface survivors
    6. Persist results and update state
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        output_dir: str = "/tmp/edge_discovery",
        data_path: str = "",
        max_workers: Optional[int] = None,
        backlog_path: Optional[str] = None,
        strategies_dir: Optional[str] = None,
    ):
        self.config = config or _default_config()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_path = data_path
        self.max_workers = max_workers or max(1, cpu_count() - 1)
        self.backlog_path = backlog_path
        self.strategies_dir = strategies_dir

        self.generator = HypothesisGenerator(seed=int(time.time()) % 10000)

        # State
        self.all_hypotheses: dict[str, EdgeHypothesis] = {}
        self.survivors: list[EdgeHypothesis] = []
        self.killed: list[EdgeHypothesis] = []
        self.cycle_count = 0

        # Load persisted state if it exists
        self._load_state()

        logger.info(
            "EdgeDiscoveryEngine initialized: output=%s, workers=%d",
            self.output_dir, self.max_workers,
        )

    def run_cycle(
        self,
        max_hypotheses: int = 50,
        cycle_timeout: int = 3600,
    ) -> dict:
        """
        Run one full discovery cycle.

        Returns a summary dict with survivors, kills, and metrics.
        """
        self.cycle_count += 1
        cycle_id = f"EDC_{self.cycle_count:04d}_{int(time.time())}"
        t0 = time.monotonic()

        logger.info("=== Edge Discovery Cycle %s ===", cycle_id)

        # Step 1: Generate hypotheses
        candidates = self.generator.generate_all(
            max_hypotheses=max_hypotheses,
            backlog_path=self.backlog_path,
            strategies_dir=self.strategies_dir,
        )

        # Filter out already-tested hypotheses
        new_candidates = [
            h for h in candidates
            if h.hypothesis_id not in self.all_hypotheses
        ]

        logger.info(
            "Cycle %s: %d candidates, %d new",
            cycle_id, len(candidates), len(new_candidates),
        )

        if not new_candidates:
            logger.info("No new hypotheses to test. Cycle complete.")
            return self._cycle_summary(cycle_id, [], [], t0)

        # Step 2: Parallel evaluation
        eval_config = {
            "train_window_days": self.config.get("train_window_days", 30),
            "test_window_days": self.config.get("test_window_days", 10),
            "step_size_days": self.config.get("step_size_days", 7),
            "n_windows": self.config.get("n_windows", 4),
        }

        raw_results = self._evaluate_parallel(
            new_candidates,
            eval_config,
            timeout_sec=cycle_timeout,
        )

        # Step 3: BH-FDR correction across this batch
        p_values = [r.get("approx_p_value", 0.5) for r in raw_results]
        bh_mask = benjamini_hochberg(p_values, alpha=self.config.get("bh_fdr_alpha", 0.10))

        # Step 4: Update hypothesis states
        cycle_survivors = []
        cycle_killed = []

        for hyp, result, bh_pass in zip(new_candidates, raw_results, bh_mask):
            hyp.posterior = result.get("posterior_dict")
            hyp.walk_forward_windows = len(result.get("windows", []))
            hyp.opportunity_density_per_day = result.get("opportunity_density_per_day", 0.0)
            hyp.fill_rate_estimate = result.get("fill_rate_ok", False) and 0.25 or 0.10
            hyp.max_drawdown = result.get("max_drawdown", 1.0)
            hyp.net_pnl_after_fees = result.get("avg_net_pnl_per_window", 0.0)

            bh_result = result.copy()
            bh_result["bh_fdr_passes"] = bh_pass

            kill_reason = result.get("kill_reason")
            is_survivor = result.get("is_survivor", False) and bh_pass

            if kill_reason or not bh_pass:
                hyp.status = "killed"
                hyp.kill_reason = kill_reason or "bh_fdr_rejected"
                cycle_killed.append(hyp)
                self.killed.append(hyp)
            elif is_survivor:
                hyp.status = "survivor"
                hyp.promoted_at = datetime.now(timezone.utc)
                cycle_survivors.append(hyp)
                self.survivors.append(hyp)
            else:
                # Insufficient data — keep as pending for next cycle
                hyp.status = "pending"

            self.all_hypotheses[hyp.hypothesis_id] = hyp

        # Step 5: Persist state and report
        self._save_state()
        summary = self._cycle_summary(cycle_id, cycle_survivors, cycle_killed, t0)
        self._save_cycle_report(cycle_id, summary, raw_results, new_candidates)

        logger.info(
            "Cycle %s complete: %d survivors, %d killed, %d pending, %.1fs",
            cycle_id,
            len(cycle_survivors),
            len(cycle_killed),
            len(new_candidates) - len(cycle_survivors) - len(cycle_killed),
            time.monotonic() - t0,
        )

        return summary

    def _evaluate_parallel(
        self,
        hypotheses: list[EdgeHypothesis],
        eval_config: dict,
        timeout_sec: int = 3600,
    ) -> list[dict]:
        """Evaluate hypotheses in parallel using ProcessPoolExecutor."""
        work_items = [
            (h.to_dict(), self.data_path, eval_config)
            for h in hypotheses
        ]

        results_map: dict[str, dict] = {}

        if self.max_workers <= 1 or len(hypotheses) <= 2:
            # Sequential for debugging or small batches
            for item, hyp in zip(work_items, hypotheses):
                result = _evaluate_hypothesis_worker(item)
                results_map[hyp.hypothesis_id] = result
        else:
            deadline = time.monotonic() + timeout_sec

            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_hyp = {
                    executor.submit(_evaluate_hypothesis_worker, item): hyp
                    for item, hyp in zip(work_items, hypotheses)
                }

                for future in as_completed(future_to_hyp, timeout=timeout_sec):
                    hyp = future_to_hyp[future]
                    try:
                        result = future.result(timeout=max(1, deadline - time.monotonic()))
                        results_map[hyp.hypothesis_id] = result
                    except Exception as e:
                        logger.error("Hypothesis %s eval failed: %s", hyp.hypothesis_id, e)
                        results_map[hyp.hypothesis_id] = {
                            "hypothesis_id": hyp.hypothesis_id,
                            "kill_reason": f"eval_error: {str(e)[:100]}",
                            "is_survivor": False,
                            "approx_p_value": 1.0,
                            "prob_positive": 0.5,
                            "total_simulated_trades": 0,
                            "avg_net_pnl_per_window": 0.0,
                            "opportunity_density_per_day": 0.0,
                            "max_drawdown": 1.0,
                            "net_edge_positive": False,
                            "fee_stress_survives": False,
                            "density_ok": False,
                            "fill_rate_ok": False,
                            "drawdown_ok": False,
                            "bh_fdr_passes": False,
                            "windows": [],
                            "posterior_dict": {"n": 0, "prob_positive": 0.5},
                        }

        # Return in original order
        ordered = []
        for hyp in hypotheses:
            ordered.append(results_map.get(hyp.hypothesis_id, {
                "hypothesis_id": hyp.hypothesis_id,
                "kill_reason": "timeout",
                "is_survivor": False,
                "approx_p_value": 1.0,
                "prob_positive": 0.5,
                "total_simulated_trades": 0,
                "windows": [],
                "posterior_dict": {"n": 0, "prob_positive": 0.5},
            }))
        return ordered

    def _cycle_summary(
        self,
        cycle_id: str,
        survivors: list[EdgeHypothesis],
        killed: list[EdgeHypothesis],
        t0: float,
    ) -> dict:
        return {
            "cycle_id": cycle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": round(time.monotonic() - t0, 1),
            "cycle_count": self.cycle_count,
            "total_hypotheses_ever": len(self.all_hypotheses),
            "total_survivors_ever": len(self.survivors),
            "total_killed_ever": len(self.killed),
            "this_cycle_survivors": len(survivors),
            "this_cycle_killed": len(killed),
            "survivors": [
                {
                    "id": h.hypothesis_id,
                    "family": h.strategy_family,
                    "venue": h.venue,
                    "prob_positive": (h.posterior or {}).get("prob_positive", 0),
                    "density": h.opportunity_density_per_day,
                    "net_pnl": h.net_pnl_after_fees,
                }
                for h in survivors
            ],
            "top_killed": [
                {
                    "id": h.hypothesis_id,
                    "reason": h.kill_reason,
                    "prob_positive": (h.posterior or {}).get("prob_positive", 0),
                }
                for h in sorted(killed, key=lambda h: (h.posterior or {}).get("prob_positive", 0), reverse=True)[:5]
            ],
        }

    def _save_cycle_report(
        self,
        cycle_id: str,
        summary: dict,
        raw_results: list[dict],
        hypotheses: list[EdgeHypothesis],
    ) -> None:
        """Save full cycle report to disk."""
        report = {
            "summary": summary,
            "hypotheses": [h.to_dict() for h in hypotheses],
            "raw_results": raw_results,
        }

        path = self.output_dir / f"{cycle_id}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        logger.debug("Cycle report saved to %s", path)

        # Also update the rolling survivors file
        survivors_path = self.output_dir / "survivors.json"
        survivors_path.write_text(json.dumps(
            [h.to_dict() for h in self.survivors],
            indent=2, default=str,
        ))

        # Human-readable markdown summary
        md_path = self.output_dir / "edge_discovery_report.md"
        md_path.write_text(_format_discovery_report_md(self))

    def _save_state(self) -> None:
        """Persist engine state for resumption."""
        state = {
            "cycle_count": self.cycle_count,
            "all_hypothesis_ids": list(self.all_hypotheses.keys()),
            "survivor_ids": [h.hypothesis_id for h in self.survivors],
            "killed_ids": [h.hypothesis_id for h in self.killed],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (self.output_dir / "state.json").write_text(
            json.dumps(state, indent=2)
        )

    def _load_state(self) -> None:
        """Load persisted state if available."""
        state_path = self.output_dir / "state.json"
        if not state_path.exists():
            return
        try:
            state = json.loads(state_path.read_text())
            self.cycle_count = state.get("cycle_count", 0)
            logger.info(
                "Resumed from state: %d prior cycles, %d survivors",
                self.cycle_count,
                len(state.get("survivor_ids", [])),
            )
        except (json.JSONDecodeError, KeyError):
            pass


def _default_config() -> dict:
    """Default engine configuration."""
    return {
        "train_window_days": 30,
        "test_window_days": 10,
        "step_size_days": 7,
        "n_windows": 4,
        "bh_fdr_alpha": 0.10,
        # Kill thresholds
        "kill_prob_positive": 0.30,
        "kill_min_trades": 30,
        "kill_fee_drag_pct": 0.50,
        "kill_density_min": 1.0,
        "kill_fill_rate_min": 0.10,
        "kill_max_dd_multiplier": 3.0,
        # Promotion thresholds
        "promote_prob_positive": 0.90,
        "promote_density_min": 2.0,
        "promote_fill_rate_min": 0.20,
        "promote_min_windows": 3,
        "promote_min_trades": 30,
    }


def _format_discovery_report_md(engine: "EdgeDiscoveryEngine") -> str:
    """Format a human-readable markdown report."""
    lines = [
        "# Edge Discovery Engine Report",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Cycles Run:** {engine.cycle_count}",
        f"**Total Hypotheses Tested:** {len(engine.all_hypotheses)}",
        f"**Survivors:** {len(engine.survivors)}",
        f"**Killed:** {len(engine.killed)}",
        "",
        "## Survivors",
        "",
        "| ID | Family | Venue | P(mu>0) | Density/day | Net PnL/window |",
        "|----|--------|-------|---------|-------------|----------------|",
    ]

    for h in sorted(engine.survivors, key=lambda x: (x.posterior or {}).get("prob_positive", 0), reverse=True):
        p = (h.posterior or {}).get("prob_positive", 0)
        lines.append(
            f"| {h.hypothesis_id[:30]} | {h.strategy_family} | {h.venue} | "
            f"{p:.3f} | {h.opportunity_density_per_day:.1f} | ${h.net_pnl_after_fees:.4f} |"
        )

    lines.extend([
        "",
        "## Kill Breakdown",
        "",
        "| Kill Reason | Count |",
        "|-------------|-------|",
    ])

    kill_counts: dict[str, int] = {}
    for h in engine.killed:
        reason_key = (h.kill_reason or "unknown").split(":")[0]
        kill_counts[reason_key] = kill_counts.get(reason_key, 0) + 1

    for reason, count in sorted(kill_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {reason} | {count} |")

    lines.extend([
        "",
        "## Family Distribution",
        "",
        "| Family | Tested | Survived | Kill Rate |",
        "|--------|--------|----------|-----------|",
    ])

    family_stats: dict[str, dict] = {}
    for h in engine.all_hypotheses.values():
        f = h.strategy_family
        if f not in family_stats:
            family_stats[f] = {"tested": 0, "survived": 0}
        family_stats[f]["tested"] += 1
        if h.status == "survivor":
            family_stats[f]["survived"] += 1

    for family, stats in sorted(family_stats.items()):
        t = stats["tested"]
        s = stats["survived"]
        kr = (t - s) / t if t > 0 else 0
        lines.append(f"| {family} | {t} | {s} | {kr:.1%} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Edge Discovery Engine — continuous hypothesis generation and kill testing"
    )
    parser.add_argument(
        "--max-hypotheses",
        type=int,
        default=20,
        help="Maximum hypotheses to test per cycle (default: 20)",
    )
    parser.add_argument(
        "--cycle-timeout",
        type=int,
        default=3600,
        help="Maximum seconds per cycle before timeout (default: 3600)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/tmp/edge_discovery",
        help="Directory for reports and state (default: /tmp/edge_discovery)",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default="",
        help="Path to historical market data JSON (synthetic if not provided)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="Path to YAML config file (optional)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Number of parallel workers (default: cpu_count - 1)",
    )
    parser.add_argument(
        "--backlog",
        type=str,
        default="",
        help="Path to edge_backlog_ranked.md (default: auto-detected)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate hypotheses only; do not evaluate",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    # Load config
    config = _default_config()
    if args.config:
        try:
            import yaml
            with open(args.config) as f:
                file_config = yaml.safe_load(f)
            config.update(file_config.get("engine", {}))
            logger.info("Loaded config from %s", args.config)
        except Exception as e:
            logger.warning("Could not load config file %s: %s", args.config, e)

    # Build engine
    engine = EdgeDiscoveryEngine(
        config=config,
        output_dir=args.output_dir,
        data_path=args.data_path,
        max_workers=args.workers if args.workers > 0 else None,
        backlog_path=args.backlog if args.backlog else None,
    )

    if args.dry_run:
        # Just generate and print hypotheses
        logger.info("DRY RUN: generating hypotheses only")
        hypotheses = engine.generator.generate_all(
            max_hypotheses=args.max_hypotheses,
            backlog_path=args.backlog if args.backlog else None,
        )
        print(f"\nGenerated {len(hypotheses)} hypotheses:")
        for h in hypotheses[:20]:
            print(f"  [{h.status}] {h.hypothesis_id}")
            print(f"    Family: {h.strategy_family} | Venue: {h.venue} | Fee: {h.fee_model}")
            print(f"    Entry: {h.entry_logic[:80]}")
            print()
        return

    # Run one cycle
    summary = engine.run_cycle(
        max_hypotheses=args.max_hypotheses,
        cycle_timeout=args.cycle_timeout,
    )

    # Print summary
    print("\n" + "=" * 60)
    print(f"EDGE DISCOVERY CYCLE COMPLETE — {summary['cycle_id']}")
    print("=" * 60)
    print(f"Elapsed: {summary['elapsed_sec']}s")
    print(f"Hypotheses tested this cycle: {summary['this_cycle_survivors'] + summary['this_cycle_killed']}")
    print(f"Survivors (this cycle): {summary['this_cycle_survivors']}")
    print(f"Killed (this cycle): {summary['this_cycle_killed']}")
    print(f"Total survivors ever: {summary['total_survivors_ever']}")
    print(f"Total killed ever: {summary['total_killed_ever']}")

    if summary["survivors"]:
        print("\n--- SURVIVORS ---")
        for s in summary["survivors"]:
            print(
                f"  {s['id'][:40]} | P(mu>0)={s['prob_positive']:.3f} | "
                f"density={s['density']:.1f}/day | net_pnl=${s['net_pnl']:.4f}"
            )

    if summary["top_killed"]:
        print("\n--- TOP KILLS (closest to surviving) ---")
        for k in summary["top_killed"]:
            print(f"  {k['id'][:40]} | {k['reason']} | P(mu>0)={k['prob_positive']:.3f}")

    print(f"\nFull report: {engine.output_dir / 'edge_discovery_report.md'}")
    print(f"Survivors:   {engine.output_dir / 'survivors.json'}")


if __name__ == "__main__":
    main()
