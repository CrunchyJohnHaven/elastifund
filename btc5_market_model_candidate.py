"""Mutable BTC5 market-model candidate surface.

This is the only file the BTC5 market-model benchmark is allowed to mutate
within an active epoch.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


CANDIDATE_CONTRACT_VERSION = 1
MUTATION_SURFACE = {'model_name': 'empirical_backoff_v1__escalated_blend',
 'model_version': 3,
 'feature_levels': [['direction', 'session_name', 'price_bucket', 'delta_bucket'],
                    ['direction', 'session_name', 'delta_bucket'],
                    ['direction', 'session_name', 'price_bucket'],
                    ['session_name', 'delta_bucket'],
                    ['direction', 'session_name'],
                    ['direction'],
                    []],
 'target_priors': {'p_up': 0.775, 'fill_rate': 0.465385, 'pnl_pct': 0.091391},
 'target_smoothing': {'p_up': 2.0, 'fill_rate': 3.0, 'pnl_pct': 4.0},
 'global_backstop_weight_min': 0.03,
 'global_backstop_weight_max': 0.62,
 'pnl_fill_blend_base': 0.42,
 'pnl_fill_blend_scale': 0.58,
 'pnl_clamp_abs': 1.8}

MODEL_NAME = str(MUTATION_SURFACE["model_name"])
MODEL_VERSION = int(MUTATION_SURFACE["model_version"])
FEATURE_LEVELS: tuple[tuple[str, ...], ...] = tuple(
    tuple(str(field) for field in fields)
    for fields in MUTATION_SURFACE["feature_levels"]
)
TARGET_PRIORS = {
    key: float(value)
    for key, value in dict(MUTATION_SURFACE["target_priors"]).items()
}
TARGET_SMOOTHING = {
    key: float(value)
    for key, value in dict(MUTATION_SURFACE["target_smoothing"]).items()
}
GLOBAL_BACKSTOP_WEIGHT_MIN = float(MUTATION_SURFACE["global_backstop_weight_min"])
GLOBAL_BACKSTOP_WEIGHT_MAX = float(MUTATION_SURFACE["global_backstop_weight_max"])
PNL_FILL_BLEND_BASE = float(MUTATION_SURFACE["pnl_fill_blend_base"])
PNL_FILL_BLEND_SCALE = float(MUTATION_SURFACE["pnl_fill_blend_scale"])
PNL_CLAMP_ABS = float(MUTATION_SURFACE["pnl_clamp_abs"])


@dataclass(frozen=True)
class _Aggregate:
    count: int
    p_up_sum: float
    fill_rate_sum: float
    pnl_pct_sum: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _row_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in fields)


def fit_market_model(
    warmup_rows: list[dict[str, Any]],
    *,
    feature_fields: list[str] | tuple[str, ...],
    seed: int = 0,
) -> dict[str, Any]:
    del feature_fields, seed
    grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], list[float]] = defaultdict(
        lambda: [0.0, 0.0, 0.0, 0.0]
    )
    global_count = 0
    global_p_up_sum = 0.0
    global_fill_rate_sum = 0.0
    global_pnl_pct_sum = 0.0

    for row in warmup_rows:
        global_count += 1
        global_p_up_sum += _safe_float(row.get("actual_side_up"), 0.5)
        global_fill_rate_sum += _safe_float(row.get("actual_fill_rate"), 0.0)
        global_pnl_pct_sum += _safe_float(row.get("actual_pnl_pct"), 0.0)
        for fields in FEATURE_LEVELS:
            key = (fields, _row_key(row, fields))
            payload = grouped[key]
            payload[0] += 1.0
            payload[1] += _safe_float(row.get("actual_side_up"), 0.5)
            payload[2] += _safe_float(row.get("actual_fill_rate"), 0.0)
            payload[3] += _safe_float(row.get("actual_pnl_pct"), 0.0)

    aggregates = {
        key: _Aggregate(
            count=int(values[0]),
            p_up_sum=float(values[1]),
            fill_rate_sum=float(values[2]),
            pnl_pct_sum=float(values[3]),
        )
        for key, values in grouped.items()
    }
    return {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "global": _Aggregate(
            count=global_count,
            p_up_sum=global_p_up_sum,
            fill_rate_sum=global_fill_rate_sum,
            pnl_pct_sum=global_pnl_pct_sum,
        ),
        "aggregates": aggregates,
    }


def _smoothed_mean(total: float, count: int, *, target: str) -> float:
    smoothing = TARGET_SMOOTHING[target]
    prior = TARGET_PRIORS[target]
    return (total + (smoothing * prior)) / float(count + smoothing)


def _blend_prediction(model: dict[str, Any], row: dict[str, Any], *, target: str) -> float:
    aggregates: dict[tuple[tuple[str, ...], tuple[str, ...]], _Aggregate] = model["aggregates"]
    global_bucket: _Aggregate = model["global"]
    weighted_sum = 0.0
    weight_total = 0.0

    for fields in FEATURE_LEVELS:
        aggregate = aggregates.get((fields, _row_key(row, fields)))
        if aggregate is None or aggregate.count <= 0:
            continue
        count = aggregate.count
        weight = float(count) / float(count + TARGET_SMOOTHING[target])
        if target == "p_up":
            estimate = _smoothed_mean(aggregate.p_up_sum, count, target=target)
        elif target == "fill_rate":
            estimate = _smoothed_mean(aggregate.fill_rate_sum, count, target=target)
        else:
            estimate = _smoothed_mean(aggregate.pnl_pct_sum, count, target=target)
        weighted_sum += weight * estimate
        weight_total += weight

    if weight_total <= 0.0 or global_bucket.count <= 0:
        return TARGET_PRIORS[target]

    global_estimate = _smoothed_mean(
        global_bucket.p_up_sum
        if target == "p_up"
        else global_bucket.fill_rate_sum
        if target == "fill_rate"
        else global_bucket.pnl_pct_sum,
        global_bucket.count,
        target=target,
    )
    global_weight = max(
        GLOBAL_BACKSTOP_WEIGHT_MIN,
        1.0 - min(GLOBAL_BACKSTOP_WEIGHT_MAX, weight_total),
    )
    return ((weighted_sum + (global_weight * global_estimate)) / (weight_total + global_weight))


def predict_market_row(
    model: dict[str, Any],
    row: dict[str, Any],
    *,
    feature_fields: list[str] | tuple[str, ...],
) -> dict[str, float]:
    del feature_fields
    p_up = _clamp(_blend_prediction(model, row, target="p_up"), 0.001, 0.999)
    fill_rate = _clamp(_blend_prediction(model, row, target="fill_rate"), 0.0, 1.0)
    pnl_pct = _blend_prediction(model, row, target="pnl_pct")
    pnl_pct *= PNL_FILL_BLEND_BASE + (PNL_FILL_BLEND_SCALE * fill_rate)
    pnl_pct = _clamp(pnl_pct, -PNL_CLAMP_ABS, PNL_CLAMP_ABS)
    return {
        "p_up": p_up,
        "fill_rate": fill_rate,
        "pnl_pct": pnl_pct,
    }
