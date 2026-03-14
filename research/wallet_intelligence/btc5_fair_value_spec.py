#!/usr/bin/env python3
"""
BTC5 Fair Value Pricing Engine — Production Spec
=================================================
Implements the pricing model from ChatGPT Prompt 3 research output.

Model stack (priority order):
  1. Clean cross-venue reference price (Binance + Coinbase)
  2. 1-second rolling/EWMA realized variance (primary)
  3. GARCH(1,1) regime prior (secondary, slower)
  4. Student-t baseline / Merton jump overlay (tail risk)
  5. Fill probability + adverse-selection EV model

Key insight from research: For near-expiry BTC binaries, one bad basis
point in the reference price is often more expensive than a mediocre
volatility model. Priority is: reference price > error bars > adverse
selection > tail model.

Fee adjustment: BTC5 crypto markets launched Feb 12, 2026 with taker
fees peaking at 1.56% around 50c. All EV calculations must be
fee-adjusted using the per-token fee-rate CLOB endpoint.

March 14, 2026 — Elastifund Autoresearch (from ChatGPT Prompt 3)
"""

import math
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger("BTC5FairValue")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ANNUALIZED_SECONDS = 365.25 * 24 * 3600  # seconds in a year
PHI_0 = 1.0 / math.sqrt(2 * math.pi)  # phi(0) = 0.3989


# ---------------------------------------------------------------------------
# Normal CDF (no scipy dependency)
# ---------------------------------------------------------------------------
def norm_cdf(x: float) -> float:
    """Standard normal CDF using Abramowitz-Stegun approximation."""
    if x < -8:
        return 0.0
    if x > 8:
        return 1.0
    # Rational approximation (Horner form)
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422802 * math.exp(-0.5 * x * x)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 +
        t * (-1.821256 + t * 1.330274))))
    return 1.0 - p if x > 0 else p


def norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def student_t_cdf(x: float, nu: float = 7.0) -> float:
    """Standardized Student-t CDF (unit variance), approximate.

    Uses the normal CDF with a Cornish-Fisher-style correction for
    moderate nu. For production, use scipy.stats.t when available.
    """
    # Scale to unit variance: Student-t with nu df has variance nu/(nu-2)
    scale = math.sqrt(nu / (nu - 2)) if nu > 2 else 1.0
    z = x * scale  # rescale to standard t
    # Hill approximation for t-distribution CDF
    a = nu - 0.5
    b = 48.0 * a * a
    z2 = z * z
    y = z2 / nu
    if y > 0.04:
        y = a * math.log(1 + y)
    else:
        y = a * y * (1 - y * (0.5 - y / 3.0))
    p = -2.0 * y
    if abs(p) < 500:
        p = math.exp(p)
    else:
        p = 0.0
    return norm_cdf(z * (1 - 1.0 / (4 * nu)) if nu > 4 else z)


# ---------------------------------------------------------------------------
# 1. Reference Price Calculator
# ---------------------------------------------------------------------------
@dataclass
class VenueBook:
    """Top-of-book from one venue."""
    venue: str
    best_bid: float
    best_ask: float
    bid_qty: float
    ask_qty: float
    exchange_ts_ms: int  # exchange timestamp in milliseconds
    local_ts_ms: int     # local receive timestamp


@dataclass
class ReferencePrice:
    """Cleaned cross-venue reference price."""
    price: float
    confidence: float  # 0-1
    stale: bool
    venues_active: int
    divergence_flag: bool  # True if venues disagree > threshold
    noise_estimate_bps: float  # estimated reference noise in basis points


def clean_venue_mid(book: VenueBook, lambda_m: float = 0.7) -> float:
    """Compute blended mid/microprice for one venue.

    microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
    blended = lambda_m * plain_mid + (1-lambda_m) * microprice
    """
    mid = 0.5 * (book.best_bid + book.best_ask)
    total_qty = book.bid_qty + book.ask_qty
    if total_qty > 0:
        micro = (book.best_ask * book.bid_qty +
                 book.best_bid * book.ask_qty) / total_qty
    else:
        micro = mid
    return lambda_m * mid + (1 - lambda_m) * micro


def aggregate_reference(books: list[VenueBook],
                        now_ms: int,
                        hard_stale_ms: int = 1000,
                        soft_stale_ms: int = 250,
                        outlier_bps: float = 2.0,
                        divergence_bps: float = 5.0,
                        ) -> ReferencePrice:
    """Cross-venue weighted reference price.

    Weight formula: w_i = sqrt(depth_i) / spread_i^2 * exp(-lambda * age_i)
    """
    venue_vals: list[tuple[float, float, str]] = []  # (mid, weight, venue)

    for book in books:
        age_ms = now_ms - book.exchange_ts_ms
        if age_ms > hard_stale_ms:
            continue

        m = clean_venue_mid(book)
        spread = max(book.best_ask - book.best_bid, 1e-8)
        depth = book.bid_qty + book.ask_qty
        weight = math.sqrt(max(depth, 0.01)) / (spread ** 2) * math.exp(-0.003 * age_ms)
        venue_vals.append((m, weight, book.venue))

    if not venue_vals:
        # All stale
        return ReferencePrice(
            price=0.0, confidence=0.0, stale=True,
            venues_active=0, divergence_flag=True, noise_estimate_bps=10.0,
        )

    # Outlier filter
    mids = [m for m, _, _ in venue_vals]
    median_mid = sorted(mids)[len(mids) // 2]
    filtered = [(m, w, v) for m, w, v in venue_vals
                if abs(m / median_mid - 1) * 10000 < outlier_bps * 5]

    if not filtered:
        filtered = venue_vals  # keep all if filter too aggressive

    total_weight = sum(w for _, w, _ in filtered)
    ref_price = sum(m * w for m, w, _ in filtered) / total_weight if total_weight > 0 else median_mid

    # Divergence check
    divergence = False
    if len(filtered) >= 2:
        min_mid = min(m for m, _, _ in filtered)
        max_mid = max(m for m, _, _ in filtered)
        if ref_price > 0:
            divergence = (max_mid - min_mid) / ref_price * 10000 > divergence_bps

    # Noise estimate (cross-venue disagreement)
    if len(filtered) >= 2:
        deviations = [(m - ref_price) / ref_price * 10000 for m, _, _ in filtered]
        noise_bps = float(np.std(deviations))
    else:
        noise_bps = 0.5  # single-venue default

    return ReferencePrice(
        price=ref_price,
        confidence=min(1.0, len(filtered) / 2.0),
        stale=False,
        venues_active=len(filtered),
        divergence_flag=divergence,
        noise_estimate_bps=noise_bps,
    )


# ---------------------------------------------------------------------------
# 2. Volatility Estimation
# ---------------------------------------------------------------------------
@dataclass
class VolState:
    """Running volatility state updated every second."""
    ewma_var: float = 0.0
    garch_var: float = 0.0
    returns_buffer: list = field(default_factory=list)
    buffer_max: int = 600  # 10 minutes of 1-second returns

    # GARCH params (refit periodically, not every second)
    omega: float = 1e-10
    alpha: float = 0.10
    beta: float = 0.88

    # EWMA decay
    ewma_lambda: float = 0.94

    # Blend weight (high = favor rolling, low = favor GARCH)
    blend_weight: float = 0.7


def update_volatility(state: VolState, log_return: float,
                      tau_seconds: float) -> float:
    """Update vol state with new 1-second return, return horizon variance.

    Returns v_hat = estimated variance over tau_seconds remaining.
    """
    r2 = log_return * log_return

    # EWMA update
    state.ewma_var = (1 - state.ewma_lambda) * r2 + state.ewma_lambda * state.ewma_var

    # GARCH update
    state.garch_var = state.omega + state.alpha * r2 + state.beta * state.garch_var

    # Store return
    state.returns_buffer.append(log_return)
    if len(state.returns_buffer) > state.buffer_max:
        state.returns_buffer.pop(0)

    # Rolling variance (for cross-check)
    if len(state.returns_buffer) >= 30:
        roll_var = float(np.var(state.returns_buffer[-300:], ddof=1))
    else:
        roll_var = state.ewma_var

    # Horizon forecasts
    v_ewma = tau_seconds * state.ewma_var
    # GARCH multi-step: sum of E[sigma^2_{t+j}] for j=1..tau
    ab = state.alpha + state.beta
    long_run_var = state.omega / max(1 - ab, 1e-10)
    v_garch = 0.0
    if abs(ab) < 1:
        # Geometric series
        if abs(1 - ab) > 1e-10:
            v_garch = long_run_var * tau_seconds + \
                (state.garch_var - long_run_var) * (1 - ab ** tau_seconds) / (1 - ab)
        else:
            v_garch = state.garch_var * tau_seconds
    else:
        v_garch = state.garch_var * tau_seconds

    # Blend
    v_hat = state.blend_weight * v_ewma + (1 - state.blend_weight) * v_garch
    return max(v_hat, 1e-16)  # floor to avoid sqrt(0)


# ---------------------------------------------------------------------------
# 3. GBM Probability
# ---------------------------------------------------------------------------
def gbm_prob(S: float, K: float, v: float, mu_adj: float = 0.0) -> float:
    """P(S_T > K) under GBM with variance v = sigma^2 * tau.

    mu_adj is the drift adjustment (negligible for 5-min horizon).
    """
    if v <= 0 or S <= 0 or K <= 0:
        return 0.5

    sqrt_v = math.sqrt(v)
    z = (math.log(S / K) + mu_adj - 0.5 * v) / sqrt_v
    return norm_cdf(z)


# ---------------------------------------------------------------------------
# 4. Tail Adjustments
# ---------------------------------------------------------------------------
def student_t_prob(S: float, K: float, v: float, nu: float = 7.0) -> float:
    """P(S_T > K) using Student-t innovations (unit-variance matched)."""
    if v <= 0 or S <= 0 or K <= 0:
        return 0.5

    sqrt_v = math.sqrt(v)
    z = (math.log(S / K) - 0.5 * v) / sqrt_v
    return student_t_cdf(z, nu)


def merton_jump_prob(S: float, K: float, v: float,
                     lam: float = 0.5,  # jump intensity (per 5-min)
                     mu_j: float = 0.0,  # mean jump size
                     sigma_j: float = 0.005,  # jump size vol
                     n_max: int = 4,
                     ) -> float:
    """P(S_T > K) under Merton jump-diffusion.

    Poisson mixture of GBM probabilities conditional on n jumps.
    """
    tau_seconds = v / max(v, 1e-16)  # approximate
    kappa = math.exp(mu_j + 0.5 * sigma_j ** 2) - 1
    base_drift = -lam * kappa - 0.5 * v / max(tau_seconds, 1)

    prob = 0.0
    poisson_weight_sum = 0.0

    for n in range(n_max + 1):
        # Poisson weight
        lt = lam  # already per-window
        pw = math.exp(-lt) * (lt ** n) / math.factorial(n)
        poisson_weight_sum += pw

        # Conditional mean and variance
        cond_mean = math.log(S / K) + base_drift * tau_seconds + n * mu_j
        cond_var = v + n * sigma_j ** 2

        if cond_var > 0:
            z = (cond_mean - 0.5 * cond_var) / math.sqrt(cond_var)
            prob += pw * norm_cdf(z)

    return prob


# ---------------------------------------------------------------------------
# 5. Jump Detection
# ---------------------------------------------------------------------------
def detect_jump(latest_return: float, current_var: float,
                threshold: float = 4.0) -> bool:
    """Fire jump alarm when standardized return exceeds threshold."""
    if current_var <= 0:
        return False
    j_score = abs(latest_return) / math.sqrt(current_var)
    return j_score > threshold


# ---------------------------------------------------------------------------
# 6. Model Error / Confidence
# ---------------------------------------------------------------------------
def probability_standard_error(S: float, K: float, v: float,
                                ref_noise_bps: float) -> float:
    """Approximate standard error of model probability estimate.

    Uses delta-method: Var(p) ~ (dp/dx)^2 * Var(x) + (dp/dsigma)^2 * Var(sigma)
    Dominantly: SE(p) ~ phi(z) / sqrt(v) * sigma_x
    """
    if v <= 0 or S <= 0 or K <= 0:
        return 1.0

    sqrt_v = math.sqrt(v)
    z = (math.log(S / K) - 0.5 * v) / sqrt_v
    phi_z = norm_pdf(z)

    # Reference noise in log-price units
    sigma_x = ref_noise_bps * 1e-4

    # dp/dx = phi(z) / sqrt(v)
    dp_dx = phi_z / sqrt_v

    se = dp_dx * sigma_x
    return max(se, 1e-6)


def min_tau_for_edge(edge_cents: float, ref_noise_bps: float,
                     sigma_annual: float = 0.80,
                     confidence: float = 0.90) -> float:
    """Minimum seconds remaining to identify an edge of given size.

    From research: SE(p) <= edge / z_alpha
    Near ATM: SE(p) ~ phi(0) * sigma_x / (sigma * sqrt(tau))
    => tau >= (phi(0) * sigma_x / (edge/z_alpha * sigma))^2
    """
    from math import sqrt

    z_alpha = 1.645 if confidence == 0.90 else 1.96
    sigma_x = ref_noise_bps * 1e-4
    edge = edge_cents / 100.0
    sigma_per_sec = sigma_annual / sqrt(ANNUALIZED_SECONDS)

    threshold = edge / z_alpha
    if threshold <= 0 or sigma_per_sec <= 0:
        return 300.0

    tau = (PHI_0 * sigma_x / (threshold * sigma_per_sec)) ** 2
    return min(tau, 300.0)


# ---------------------------------------------------------------------------
# 7. Fee-Adjusted Expected Value
# ---------------------------------------------------------------------------
def btc5_fee_rate(price: float) -> float:
    """Approximate BTC5 taker fee rate.

    Fee curve peaks at ~1.56% around 50c, falls toward 0/1.
    Approximation: fee = 0.0156 * 4 * p * (1-p) for taker.
    Maker rebate is typically negative (you get paid).
    """
    return 0.0156 * 4.0 * price * (1.0 - price)


def maker_order_ev(quote_price: float, p_model: float,
                   fill_prob: float,
                   adverse_selection: float = 0.01,
                   maker_fee: float = -0.001,  # negative = rebate
                   ) -> float:
    """Expected value of a maker YES buy order at quote_price.

    EV = P_fill * (p_model - gamma_adv - quote - fee)
    """
    ev_if_filled = p_model - adverse_selection - quote_price - maker_fee
    return fill_prob * ev_if_filled


def should_quote(p_model: float, quote_price: float,
                 se_p: float, fill_prob: float,
                 adverse_selection: float = 0.01,
                 maker_fee: float = -0.001,
                 significance_z: float = 1.645,
                 ) -> Tuple[bool, float]:
    """Decision: should we place a maker order at this price?

    Two conditions must hold:
      1. EV > 0
      2. |p_model - quote| / SE(p) > z_threshold (edge is real)

    Returns (should_trade, ev).
    """
    ev = maker_order_ev(quote_price, p_model, fill_prob,
                        adverse_selection, maker_fee)

    edge_significance = abs(p_model - quote_price) / max(se_p, 1e-6)

    return (ev > 0 and edge_significance > significance_z), ev


# ---------------------------------------------------------------------------
# 8. Main Fair Value Function
# ---------------------------------------------------------------------------
def compute_fair_value(
    S: float,          # reference price (cleaned)
    K: float,          # strike price
    tau_seconds: float, # seconds remaining
    vol_state: VolState,
    latest_return: float,
    ref_noise_bps: float = 0.5,
    nu: float = 7.0,   # Student-t degrees of freedom
) -> Tuple[float, float, bool]:
    """Compute fair value probability for BTC5 binary.

    Returns: (p_model, standard_error, jump_mode)
    """
    # Variance forecast
    v = update_volatility(vol_state, latest_return, tau_seconds)

    # Jump detection
    jump_mode = detect_jump(latest_return, vol_state.ewma_var)

    # Base probability
    if jump_mode:
        p_raw = merton_jump_prob(S, K, v)
    else:
        p_raw = student_t_prob(S, K, v, nu=nu)

    # Standard error
    se = probability_standard_error(S, K, v, ref_noise_bps)

    # Clamp to [0.01, 0.99] for safety
    p_model = max(0.01, min(0.99, p_raw))

    return p_model, se, jump_mode


# ---------------------------------------------------------------------------
# Sweet spot analysis (from research Section 6)
# ---------------------------------------------------------------------------
def sweet_spot_analysis(sigma_annual: float = 0.80,
                        ref_noise_bps: float = 0.5) -> dict:
    """Compute actionable time windows from research findings.

    Near ATM, sweet spot is 30-120 seconds remaining.
    Further OTM, precision improves rapidly.
    """
    sigma_per_sec = sigma_annual / math.sqrt(ANNUALIZED_SECONDS)

    results = {}
    for edge_cents in [1, 2, 3, 5]:
        tau = min_tau_for_edge(edge_cents, ref_noise_bps, sigma_annual)
        results[f"{edge_cents}c_edge_min_seconds"] = round(tau, 1)

    # 5-min diffusive std dev at different vol regimes
    for ann_vol in [0.40, 0.80, 1.20]:
        std_5m = ann_vol / math.sqrt(ANNUALIZED_SECONDS) * math.sqrt(300) * 10000
        results[f"5m_std_bps_at_{int(ann_vol*100)}pct_vol"] = round(std_5m, 1)

    return results


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test basic pricing
    S = 84000.0  # BTC price
    K = 84010.0  # strike 10 above

    vol_state = VolState()
    vol_state.ewma_var = (0.80 / math.sqrt(ANNUALIZED_SECONDS)) ** 2  # init

    p, se, jump = compute_fair_value(S, K, 300, vol_state, 0.0001)
    print(f"Fair value: {p:.4f} (SE: {se:.4f}, jump: {jump})")

    p60, se60, _ = compute_fair_value(S, K, 60, vol_state, 0.0001)
    print(f"At 60s remaining: {p60:.4f} (SE: {se60:.4f})")

    p10, se10, _ = compute_fair_value(S, K, 10, vol_state, 0.0001)
    print(f"At 10s remaining: {p10:.4f} (SE: {se10:.4f})")

    # Sweet spot
    sweet = sweet_spot_analysis()
    print(f"\nSweet spot analysis:")
    for k, v in sweet.items():
        print(f"  {k}: {v}")

    # EV test
    should, ev = should_quote(p, 0.45, se, fill_prob=0.3)
    print(f"\nShould quote at 0.45? {should} (EV: {ev:.4f})")
