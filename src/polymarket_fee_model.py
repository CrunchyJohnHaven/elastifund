"""Shared Polymarket fee and maker-rebate helpers."""

from __future__ import annotations

from dataclasses import dataclass


CRYPTO_TAKER_FEE_RATE = 0.25
CRYPTO_TAKER_FEE_EXPONENT = 2.0

LINEAR_TAKER_FEE_MODELS = {
    "sports": 0.0175,
    "default": 0.0,
}

MAKER_REBATE_SHARES = {
    "crypto": 0.20,
    "sports": 0.25,
    "default": 0.0,
}


@dataclass(frozen=True)
class FeeBreakdown:
    probability: float
    category: str
    effective_taker_rate: float
    taker_fee_amount: float
    maker_rebate_amount: float
    maker_rebate_share: float


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, float(value)))


def effective_taker_rate(probability: float, category: str) -> float:
    normalized_category = str(category or "").strip().lower() or "default"
    p = _clamp_probability(probability)
    uncertainty = p * (1.0 - p)
    if normalized_category == "crypto":
        return float(CRYPTO_TAKER_FEE_RATE * (uncertainty ** CRYPTO_TAKER_FEE_EXPONENT))
    base_rate = float(
        LINEAR_TAKER_FEE_MODELS.get(normalized_category, LINEAR_TAKER_FEE_MODELS["default"])
    )
    return float(base_rate * uncertainty)


def taker_fee_amount(probability: float, category: str, *, shares: float = 1.0) -> float:
    p = _clamp_probability(probability)
    return float(max(0.0, shares) * p * effective_taker_rate(p, category))


def maker_rebate_amount(probability: float, category: str, *, shares: float = 1.0) -> float:
    normalized_category = str(category or "").strip().lower() or "default"
    rebate_share = float(
        MAKER_REBATE_SHARES.get(normalized_category, MAKER_REBATE_SHARES["default"])
    )
    return float(taker_fee_amount(probability, normalized_category, shares=shares) * rebate_share)


def build_fee_breakdown(probability: float, category: str, *, shares: float = 1.0) -> FeeBreakdown:
    normalized_category = str(category or "").strip().lower() or "default"
    p = _clamp_probability(probability)
    rate = effective_taker_rate(p, normalized_category)
    taker_fee = taker_fee_amount(p, normalized_category, shares=shares)
    rebate_share = float(
        MAKER_REBATE_SHARES.get(normalized_category, MAKER_REBATE_SHARES["default"])
    )
    rebate = taker_fee * rebate_share
    return FeeBreakdown(
        probability=p,
        category=normalized_category,
        effective_taker_rate=rate,
        taker_fee_amount=taker_fee,
        maker_rebate_amount=rebate,
        maker_rebate_share=rebate_share,
    )
