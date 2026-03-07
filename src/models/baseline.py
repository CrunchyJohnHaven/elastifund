"""Baseline probability models for Polymarket BTC direction markets."""

from __future__ import annotations

from dataclasses import dataclass
import math


def normal_cdf(x: float) -> float:
    """Standard normal CDF using the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def inverse_normal_cdf(p: float) -> float:
    """Approximate inverse normal CDF (Acklam approximation)."""
    if p <= 0.0:
        return -10.0
    if p >= 1.0:
        return 10.0

    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    plow = 0.02425
    phigh = 1 - plow

    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )

    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


@dataclass
class ClosedFormInput:
    current_price: float
    open_price: float
    mu_per_sec: float
    sigma_per_sqrt_sec: float
    time_remaining_sec: float


def closed_form_up_probability(inputs: ClosedFormInput) -> float:
    """Closed-form probability that BTC closes above open price at horizon end."""
    if inputs.current_price <= 0.0 or inputs.open_price <= 0.0:
        return 0.5

    delta = max(inputs.time_remaining_sec, 1.0)
    sigma = max(inputs.sigma_per_sqrt_sec, 1e-8)

    numerator = math.log(inputs.current_price / inputs.open_price)
    numerator += (inputs.mu_per_sec - 0.5 * (sigma**2)) * delta
    denominator = sigma * math.sqrt(delta)
    z = numerator / max(denominator, 1e-8)
    return min(0.999, max(0.001, normal_cdf(z)))


def implied_volatility(
    market_prob: float,
    current_price: float,
    open_price: float,
    mu_per_sec: float,
    time_remaining_sec: float,
) -> float:
    """Infer implied volatility from market probability and current state."""
    p = min(0.999, max(0.001, market_prob))
    delta = max(time_remaining_sec, 1.0)
    z = inverse_normal_cdf(p)
    if abs(z) < 1e-6:
        z = 1e-6

    numerator = abs(math.log(max(current_price, 1e-8) / max(open_price, 1e-8)) + mu_per_sec * delta)
    sigma = numerator / (abs(z) * math.sqrt(delta))
    return max(sigma, 1e-8)


def naive_market_probability(yes_price: float) -> float:
    """Naive benchmark: market price is already fair probability."""
    return min(0.999, max(0.001, yes_price))
