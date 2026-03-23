#!/usr/bin/env python3
"""
Bayesian Log-Growth Promoter — Replace Win-Rate Gates with Real Math
=====================================================================
The existing promotion gates use win rate, profit factor, and binomial
tests. These are wrong for tiny samples. A strategy with 52% WR over
50 fills is indistinguishable from noise.

The correct promotion criterion is:
  P(μ_ℓ > 0 | D) >= 0.95

Where μ_ℓ is the mean log return per trade, and D is all observed data.
This uses a conjugate Normal-InverseGamma posterior (Student-t marginal)
that handles unknown variance correctly with small samples.

Kill criterion:
  P(μ_ℓ > 0 | D) < 0.20 AND n >= 15

Hold criterion (neither promote nor kill):
  Everything else. Keep gathering data.

This replaces false-kill and false-promote errors with a mathematically
honest "I don't know yet" state that is essential at tiny bankroll.

Integration with existing PromotionManager:
  - Adds a new gate type: BayesianLogGrowthGate
  - Existing execution health gates (fill rate, drawdown, slippage) remain
  - Only the EDGE QUALITY gate changes from win-rate to posterior log-growth
  - Promotion events still flow through the same SQLite schema

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("JJ.bayesian_promoter")


# ---------------------------------------------------------------------------
# Student-t posterior for mean log return
# ---------------------------------------------------------------------------

@dataclass
class LogGrowthPosterior:
    """
    Conjugate Normal-InverseGamma posterior for mean log return.

    Prior: μ ~ N(μ_0, σ²/κ_0), σ² ~ IG(α_0, β_0)
    Marginal posterior: μ | D ~ Student-t(2α_n, μ_n, β_n/(α_n * κ_n))

    We use weakly informative priors:
    - μ_0 = 0 (no prior belief about direction)
    - κ_0 = 1 (worth 1 pseudo-observation)
    - α_0 = 2, β_0 = 0.01 (vague prior on variance, slight bias toward small variance)
    """
    # Prior hyperparameters
    mu_0: float = 0.0
    kappa_0: float = 1.0
    alpha_0: float = 2.0
    beta_0: float = 0.01

    # Sufficient statistics
    n: int = 0
    sum_x: float = 0.0
    sum_x2: float = 0.0

    def update(self, log_return: float) -> None:
        """Update posterior with a single observation."""
        self.n += 1
        self.sum_x += log_return
        self.sum_x2 += log_return * log_return

    def update_batch(self, log_returns: list[float]) -> None:
        """Update posterior with multiple observations."""
        for lr in log_returns:
            self.update(lr)

    @property
    def posterior_params(self) -> tuple[float, float, float, float]:
        """Return (mu_n, kappa_n, alpha_n, beta_n) posterior hyperparameters."""
        n = self.n
        if n == 0:
            return self.mu_0, self.kappa_0, self.alpha_0, self.beta_0

        x_bar = self.sum_x / n
        kappa_n = self.kappa_0 + n
        mu_n = (self.kappa_0 * self.mu_0 + n * x_bar) / kappa_n
        alpha_n = self.alpha_0 + n / 2.0

        # Sample variance (sum of squared deviations)
        ss = self.sum_x2 - n * x_bar * x_bar  # = Σ(x_i - x_bar)²
        beta_n = (
            self.beta_0
            + 0.5 * ss
            + 0.5 * (self.kappa_0 * n / kappa_n) * (x_bar - self.mu_0) ** 2
        )

        return mu_n, kappa_n, alpha_n, beta_n

    @property
    def posterior_mean(self) -> float:
        """Point estimate of mean log return."""
        mu_n, _, _, _ = self.posterior_params
        return mu_n

    @property
    def posterior_df(self) -> float:
        """Degrees of freedom of the Student-t marginal."""
        _, _, alpha_n, _ = self.posterior_params
        return 2.0 * alpha_n

    @property
    def posterior_scale(self) -> float:
        """Scale parameter of the Student-t marginal."""
        _, kappa_n, alpha_n, beta_n = self.posterior_params
        return math.sqrt(beta_n / (alpha_n * kappa_n)) if alpha_n > 0 and kappa_n > 0 else 1.0

    def prob_positive(self) -> float:
        """
        P(μ_ℓ > 0 | D) using the Student-t CDF.

        This is the KEY metric for promotion decisions.
        """
        mu_n, kappa_n, alpha_n, beta_n = self.posterior_params
        if alpha_n <= 0 or kappa_n <= 0 or beta_n <= 0:
            return 0.5  # Undefined, return uninformative

        nu = 2.0 * alpha_n  # degrees of freedom
        scale = math.sqrt(beta_n / (alpha_n * kappa_n))

        if scale < 1e-12:
            return 1.0 if mu_n > 0 else 0.0

        # The posterior for mu is Student-t(nu) centered at mu_n with scale.
        # P(mu > 0) = P(Z > -mu_n/scale) where Z is standard Student-t
        # = 1 - CDF(-mu_n/scale) = CDF(mu_n/scale)  [by symmetry]
        t_stat = mu_n / scale
        return _student_t_cdf(t_stat, nu)

    def credible_interval(self, prob: float = 0.90) -> tuple[float, float]:
        """Return symmetric credible interval for μ_ℓ."""
        mu_n = self.posterior_mean
        scale = self.posterior_scale
        nu = self.posterior_df

        # Approximate quantile using normal approximation for large df
        alpha = (1.0 - prob) / 2.0
        z = _inv_normal(1.0 - alpha)

        # Correction for Student-t (wider tails)
        if nu > 2:
            correction = math.sqrt(nu / (nu - 2))
        else:
            correction = 3.0  # Very wide for tiny df

        half_width = z * scale * correction
        return (mu_n - half_width, mu_n + half_width)

    def to_dict(self) -> dict[str, Any]:
        mu_n, kappa_n, alpha_n, beta_n = self.posterior_params
        return {
            "n": self.n,
            "posterior_mean": round(self.posterior_mean, 8),
            "posterior_scale": round(self.posterior_scale, 8),
            "posterior_df": round(self.posterior_df, 2),
            "prob_positive": round(self.prob_positive(), 6),
            "credible_interval_90": [round(x, 8) for x in self.credible_interval(0.90)],
            "hyperparams": {
                "mu_n": round(mu_n, 8),
                "kappa_n": round(kappa_n, 4),
                "alpha_n": round(alpha_n, 4),
                "beta_n": round(beta_n, 8),
            },
        }


# ---------------------------------------------------------------------------
# Student-t CDF (no scipy dependency)
# ---------------------------------------------------------------------------

def _student_t_cdf(t: float, nu: float) -> float:
    """
    Student-t CDF via regularized incomplete beta function.
    P(T <= t) where T ~ Student-t(nu).
    """
    if nu <= 0:
        return 0.5

    x = nu / (nu + t * t)

    if t >= 0:
        return 1.0 - 0.5 * _regularized_incomplete_beta(x, nu / 2.0, 0.5)
    else:
        return 0.5 * _regularized_incomplete_beta(x, nu / 2.0, 0.5)


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """
    I_x(a, b) = B(x; a, b) / B(a, b)
    Using continued fraction expansion (Lentz's algorithm).
    """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use symmetry for numerical stability
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)

    # Log of the prefactor: x^a * (1-x)^b / (a * B(a,b))
    ln_prefix = (
        a * math.log(x) + b * math.log(1.0 - x)
        - math.log(a)
        - _log_beta(a, b)
    )

    # Continued fraction (Lentz's method)
    cf = _beta_cf(x, a, b)

    return math.exp(ln_prefix) * cf


def _beta_cf(x: float, a: float, b: float, max_iter: int = 200, tol: float = 1e-12) -> float:
    """Continued fraction for incomplete beta (modified Lentz)."""
    tiny = 1e-30
    f = 1.0 + tiny
    c = f
    d = 0.0

    for m in range(1, max_iter + 1):
        # Even step
        m2 = 2 * m
        # a_{2m}
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        c = 1.0 + num / c
        if abs(c) < tiny:
            c = tiny
        f *= c * d

        # Odd step
        # a_{2m+1}
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

        if abs(delta - 1.0) < tol:
            return f

    return f


def _log_beta(a: float, b: float) -> float:
    """Log of the beta function using lgamma."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _inv_normal(p: float) -> float:
    """Approximate inverse normal CDF (Beasley-Springer-Moro)."""
    if p <= 0:
        return -6.0
    if p >= 1:
        return 6.0
    if abs(p - 0.5) < 1e-10:
        return 0.0

    # Rational approximation
    t = math.sqrt(-2.0 * math.log(min(p, 1.0 - p)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    result = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
    return result if p > 0.5 else -result


# ---------------------------------------------------------------------------
# Niche scoring function (from research)
# ---------------------------------------------------------------------------

@dataclass
class NicheScore:
    """
    Resource-aware niche scoring from the research:

    NicheScore_j = (g_hat * lambda * C * D) / (FeeDrag * TestCost * Ambiguity)

    Where:
    - g_hat: posterior mean log-growth
    - lambda: capital velocity (edge / time_to_resolution)
    - C: capacity (USD/day tradeable)
    - D: diversification credit (1 - max correlation with existing portfolio)
    - FeeDrag: expected fees + slippage per trade
    - TestCost: engineering hours + $ to maintain
    - Ambiguity: settlement dispute risk (0-1 scale)
    """
    niche_id: str
    g_hat: float = 0.0
    capital_velocity: float = 1.0
    capacity_usd_day: float = 100.0
    diversification_credit: float = 1.0
    fee_drag: float = 0.02
    test_cost: float = 1.0
    ambiguity: float = 0.1

    @property
    def score(self) -> float:
        numerator = max(0.0, self.g_hat) * self.capital_velocity * self.capacity_usd_day * self.diversification_credit
        denominator = max(0.001, self.fee_drag) * max(0.1, self.test_cost) * max(0.01, self.ambiguity)
        return numerator / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# Thompson sampling allocator
# ---------------------------------------------------------------------------

class ThompsonAllocator:
    """
    Thompson sampling allocation across strategy niches.

    For each niche, maintains a LogGrowthPosterior. Allocation is
    proportional to posterior samples of μ_ℓ (clipped to positive).

    This is the "bandit-style" capital allocation the research demands:
    explore uncertain niches, exploit proven ones, kill dead ones.
    """

    def __init__(self, min_allocation: float = 0.05, max_allocation: float = 0.40):
        self.posteriors: dict[str, LogGrowthPosterior] = {}
        self.min_allocation = min_allocation
        self.max_allocation = max_allocation
        self._rng_state = 42

    def register_niche(self, niche_id: str) -> None:
        if niche_id not in self.posteriors:
            self.posteriors[niche_id] = LogGrowthPosterior()

    def record_return(self, niche_id: str, net_return: float) -> None:
        """Record a single trade return (after fees/slippage)."""
        if niche_id not in self.posteriors:
            self.register_niche(niche_id)
        log_ret = math.log(1.0 + max(-0.99, net_return))
        self.posteriors[niche_id].update(log_ret)

    def record_returns(self, niche_id: str, net_returns: list[float]) -> None:
        """Record multiple trade returns."""
        for r in net_returns:
            self.record_return(niche_id, r)

    def allocate(self, total_capital: float = 1000.0) -> dict[str, float]:
        """
        Sample from each posterior, compute allocation proportional to
        positive samples. Returns {niche_id: usd_allocation}.
        """
        import random
        rng = random.Random(self._rng_state)
        self._rng_state += 1

        scores: dict[str, float] = {}
        for niche_id, posterior in self.posteriors.items():
            # Sample from posterior (approximate: use mean + noise scaled by uncertainty)
            mu = posterior.posterior_mean
            scale = posterior.posterior_scale
            sample = mu + rng.gauss(0, scale) if scale > 0 else mu
            scores[niche_id] = max(0.0, sample)

        total_score = sum(scores.values())
        if total_score <= 0:
            # Uniform allocation if nothing looks good
            n = len(scores)
            return {k: total_capital / n for k in scores} if n > 0 else {}

        allocations = {}
        for niche_id, score in scores.items():
            raw_pct = score / total_score
            clamped = max(self.min_allocation, min(self.max_allocation, raw_pct))
            allocations[niche_id] = round(clamped * total_capital, 2)

        return allocations

    def get_decisions(self) -> dict[str, dict[str, Any]]:
        """
        For each niche, return promote/hold/kill decision based on posterior.

        Promote: P(μ_ℓ > 0 | D) >= 0.95 AND n >= 10
        Kill: P(μ_ℓ > 0 | D) < 0.20 AND n >= 15
        Hold: everything else
        """
        decisions = {}
        for niche_id, posterior in self.posteriors.items():
            p_pos = posterior.prob_positive()
            n = posterior.n

            if p_pos >= 0.95 and n >= 10:
                decision = "PROMOTE"
            elif p_pos < 0.20 and n >= 15:
                decision = "KILL"
            else:
                decision = "HOLD"

            decisions[niche_id] = {
                "decision": decision,
                "prob_positive": round(p_pos, 4),
                "n_observations": n,
                "posterior_mean": round(posterior.posterior_mean, 6),
                "credible_interval": [round(x, 6) for x in posterior.credible_interval(0.90)],
            }

        return decisions

    def summary(self) -> dict[str, Any]:
        """Full summary of all niches."""
        return {
            "niches": {
                niche_id: posterior.to_dict()
                for niche_id, posterior in self.posteriors.items()
            },
            "decisions": self.get_decisions(),
            "allocations": self.allocate(),
        }


# ---------------------------------------------------------------------------
# Opportunity ledger (record rejects, not just fills)
# ---------------------------------------------------------------------------

@dataclass
class OpportunityRecord:
    """
    Every opportunity the system sees, whether traded or rejected.
    This is critical for measuring false kills and opportunity density.
    """
    timestamp: float
    niche_id: str
    market_id: str
    venue: str  # polymarket, kalshi, alpaca
    action: str  # traded, filtered, killed, insufficient_edge, no_liquidity
    reason: str
    edge_estimate: float = 0.0
    confidence: float = 0.0
    entry_price: float = 0.0
    size_usd: float = 0.0
    outcome: Optional[str] = None  # Filled in later when resolved
    net_return: Optional[float] = None  # Filled in later


class OpportunityLedger:
    """
    Append-only ledger of all opportunities (traded + rejected).

    Metrics derived:
    - Opportunity density: candidates/day by niche
    - Filter pass rate: what fraction of candidates survive filtering
    - False kill rate: rejected opportunities that would have been profitable
    - Edge distribution: how edges are distributed across niches
    """

    def __init__(self):
        self._records: list[OpportunityRecord] = []

    def record(self, opp: OpportunityRecord) -> None:
        self._records.append(opp)

    def opportunity_density(self, hours: float = 24.0) -> dict[str, float]:
        """Candidates per hour by niche."""
        cutoff = time.time() - hours * 3600
        by_niche: dict[str, int] = {}
        for r in self._records:
            if r.timestamp >= cutoff:
                by_niche[r.niche_id] = by_niche.get(r.niche_id, 0) + 1
        return {k: v / hours for k, v in by_niche.items()}

    def filter_pass_rate(self) -> dict[str, float]:
        """What fraction of opportunities per niche were traded."""
        by_niche_total: dict[str, int] = {}
        by_niche_traded: dict[str, int] = {}
        for r in self._records:
            by_niche_total[r.niche_id] = by_niche_total.get(r.niche_id, 0) + 1
            if r.action == "traded":
                by_niche_traded[r.niche_id] = by_niche_traded.get(r.niche_id, 0) + 1
        return {
            k: by_niche_traded.get(k, 0) / v
            for k, v in by_niche_total.items()
            if v > 0
        }

    def false_kill_estimate(self) -> dict[str, Any]:
        """
        Estimate false kills: rejected opportunities that resolved profitably.
        Only possible for opportunities where outcome is known.
        """
        kills_profitable = 0
        kills_total = 0
        for r in self._records:
            if r.action in ("killed", "filtered") and r.net_return is not None:
                kills_total += 1
                if r.net_return > 0:
                    kills_profitable += 1
        return {
            "total_rejected_with_outcome": kills_total,
            "would_have_been_profitable": kills_profitable,
            "false_kill_rate": kills_profitable / kills_total if kills_total > 0 else 0.0,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "total_opportunities": len(self._records),
            "density_per_hour": self.opportunity_density(),
            "filter_pass_rate": self.filter_pass_rate(),
            "false_kill_estimate": self.false_kill_estimate(),
        }
