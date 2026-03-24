"""Tail-bin assignment, posterior shrinkage, and robust sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist
import math
from typing import Iterable


def _clip_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class TailBinSpec:
    bin_id: str
    min_yes_price: float
    max_yes_price: float
    traded_side: str = "NO"
    alpha_prior: float = 8.0
    beta_prior: float = 2.0

    def contains_yes_price(self, value: float) -> bool:
        price = float(value)
        return self.min_yes_price <= price <= self.max_yes_price


@dataclass(frozen=True)
class TailPosterior:
    alpha: float
    beta: float
    wins: int
    losses: int
    mean: float
    variance: float
    lower_bound: float
    upper_bound: float
    confidence: float


def default_kalshi_longshot_bins() -> tuple[TailBinSpec, ...]:
    """Pre-registered YES-price bins for longshot-fade experiments."""
    return (
        TailBinSpec("yes_1_2c", 0.01, 0.02),
        TailBinSpec("yes_2_5c", 0.02, 0.05),
        TailBinSpec("yes_5_10c", 0.05, 0.10),
    )


def assign_tail_bin(*, yes_price: float, specs: Iterable[TailBinSpec] | None = None) -> TailBinSpec | None:
    for spec in specs or default_kalshi_longshot_bins():
        if spec.contains_yes_price(yes_price):
            return spec
    return None


def posterior_from_results(
    *,
    wins: int,
    losses: int,
    alpha_prior: float,
    beta_prior: float,
    confidence: float = 0.90,
) -> TailPosterior:
    """Build a Beta-Binomial posterior summary with a normal-approx interval."""
    if wins < 0 or losses < 0:
        raise ValueError("wins and losses must be non-negative")
    alpha = float(alpha_prior) + int(wins)
    beta = float(beta_prior) + int(losses)
    total = alpha + beta
    mean = alpha / total if total > 0 else 0.5
    variance = (alpha * beta) / ((total ** 2) * (total + 1.0)) if total > 1 else 0.0
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    spread = z * math.sqrt(max(0.0, variance))
    return TailPosterior(
        alpha=alpha,
        beta=beta,
        wins=int(wins),
        losses=int(losses),
        mean=mean,
        variance=variance,
        lower_bound=_clip_probability(mean - spread),
        upper_bound=_clip_probability(mean + spread),
        confidence=float(confidence),
    )


def robust_kelly_fraction(*, p_lower: float, entry_price: float, fraction_scale: float = 1.0) -> float:
    """Compute a conservative Kelly fraction for a binary $1 payout contract."""
    p = _clip_probability(p_lower)
    x = max(1e-9, min(0.999999, float(entry_price)))
    b = (1.0 - x) / x
    raw = p - ((1.0 - p) / b)
    return max(0.0, float(fraction_scale) * raw)

