"""Queue-aware maker fill probability model for fast markets."""

from __future__ import annotations

import math
from typing import Any

from .config import BacktestConfig
from .strategies.base import Signal


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    p = _clip(p, 1e-6, 1 - 1e-6)
    return math.log(p / (1 - p))


def _meta_float(metadata: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metadata.get(key, default))
    except Exception:
        return default


def compute_queue_aware_maker_fill_probability(signal: Signal, config: BacktestConfig) -> float:
    """Estimate maker fill probability using queue-pressure proxies from signal metadata."""
    base = _clip(float(config.maker_fill_rate), config.maker_fill_floor, config.maker_fill_ceiling)
    if not config.queue_aware_maker_fill:
        return base

    metadata = signal.metadata or {}
    if not metadata:
        return base

    score = _logit(base)

    horizon = max(60.0, float(config.maker_fill_horizon_sec))
    time_remaining = _meta_float(metadata, "time_remaining_sec", -1.0)
    if time_remaining < 0.0:
        # Some strategies only provide signal age from market start.
        signal_age = _meta_float(metadata, "signal_age_sec", 0.0)
        time_remaining = max(0.0, horizon - signal_age)

    urgency = 1.0 - _clip(time_remaining / horizon, 0.0, 1.0)
    score += float(config.maker_fill_logit_urgency) * ((urgency - 0.5) * 2.0)

    trade_count = max(0.0, _meta_float(metadata, "trade_count_60s", 0.0))
    liq_scale = max(1.0, float(config.maker_fill_liquidity_trade_count_scale))
    liq_index = math.log1p(trade_count) / math.log1p(liq_scale)
    liq_index = _clip(liq_index, 0.0, 1.5)
    score += float(config.maker_fill_logit_liquidity) * ((liq_index - 0.5) * 2.0)

    edge_norm = abs(float(signal.edge_estimate)) / max(1e-6, float(config.maker_fill_edge_scale))
    score -= float(config.maker_fill_logit_edge_penalty) * _clip(edge_norm, 0.0, 3.0)

    flow = _meta_float(metadata, "book_imbalance", _meta_float(metadata, "trade_flow_imbalance", 0.0))
    flow = _clip(flow, -1.0, 1.0)
    side_sign = 1.0 if str(signal.side).upper() == "YES" else -1.0
    alignment = side_sign * flow
    # Maker orders get picked off less when leaning against aggressive flow.
    score -= float(config.maker_fill_logit_alignment_penalty) * max(0.0, alignment)
    score += 0.5 * float(config.maker_fill_logit_alignment_penalty) * max(0.0, -alignment)

    confidence_norm = _clip((float(signal.confidence) - 0.5) / 0.5, -1.0, 1.0)
    score += float(config.maker_fill_logit_confidence) * confidence_norm * 0.5

    if bool(metadata.get("wallet_signal_fallback")):
        score -= float(config.maker_fill_fallback_penalty)

    prob = _sigmoid(score)
    return _clip(prob, float(config.maker_fill_floor), float(config.maker_fill_ceiling))
